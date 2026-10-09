"""Current-turn grounding at HTTP/SSE, with controlled providers and real SQLite."""

import asyncio
import json
from uuid import uuid4

import pytest
from sqlalchemy import func, select

from app.agents.providers.bailian import ToolCall
from app.models.agent import AgentMemoryJob
from tests.api.test_agent_chat import chat_app, completed, provider
from tests.api.test_agent_tools import ask, save_day


class PlannedModel:
    model_name = "controlled-grounding"

    def __init__(self, plan=None, *, bypass=False):
        self.plan = plan or {"kind": "business", "queries": [
            {"start": "2026-07-10", "end": "2026-07-11"},
        ]}
        self.bypass = bypass
        self.answers = []

    async def stream_plan(self, messages, schemas):
        if self.bypass:
            yield "历史营业额225欧元"
        else:
            yield ToolCall("plan-1", "plan_response", json.dumps(self.plan))

    async def stream_tools(self, messages, schemas):
        if schemas and schemas[0]["function"]["name"] == "plan_response":
            async for chunk in self.stream_plan(messages, schemas):
                yield chunk
            return
        # Also works against the old graph, where no mandatory planning exists.
        self.answers.append(messages)
        results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        overviews = [r for r in results if r.get("source") == "AnalyticsService"]
        if self.plan["kind"] == "general":
            yield "Python生成器按需产生值。"
        elif self.plan["kind"] == "clarify":
            yield "请说明希望查询的日期范围。"
        elif overviews:
            yield f'本轮营业额{overviews[-1]["income_summary"]["daily_ledger_revenue"]}欧元'
        else:
            yield "历史营业额225欧元"


async def test_unplanned_historical_amount_never_publishes_or_creates_memory_job(tmp_path):
    model = PlannedModel(bypass=True)
    async with chat_app(tmp_path, model) as (client, _, factory):
        run = await ask(client, "重新查询2026年7月10日至11日经营数据")
        assert run["status"] == "failed" and run["error_code"] == "grounding_plan"
        assert "225" not in run["output"]
        assert not model.answers
        events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
        assert "225" not in events and "event: completed" not in events
        conversation = (await client.get("/api/agent/1/conversation")).json()
        assert conversation["messages"][-1]["role"] == "user"
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(AgentMemoryJob)) == 0


async def test_business_plan_executes_fresh_queries_on_every_turn(tmp_path):
    model = PlannedModel()
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-10", 150)
        first = await ask(client, "查询2026年7月10日至11日经营情况")
        assert first["status"] == "completed" and "150欧元" in first["output"]
        # A new day changes the same requested range without editing historical chat.
        await save_day(client, "2026-07-11", 75)
        second = await ask(client, "同一期间再查一次，按刚才的顺序")
        assert second["status"] == "completed" and "225欧元" in second["output"]
        assert second["calls"] == 2
        assert any("150欧元" in m.get("content", "") for m in model.answers[-1])
        for run in (first, second):
            events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
            assert events.index('"name": "read_skill"') < events.index('"name": "store_overview"')
            assert events.index('"name": "store_overview"') < events.index("本轮营业额")
            assert "event: grounding" in events and run["id"] in events


@pytest.mark.parametrize("plan", [
    {"kind": "business", "queries": []},
    {"kind": "business", "queries": [{"start": "2026-07-11", "end": "2026-07-10"}]},
    {"kind": "business", "queries": [{"start": "2026-07-10", "end": "2026-07-11", "store_id": 2}]},
    {"kind": "general", "queries": [{"start": "2026-07-10", "end": "2026-07-11"}]},
    {"kind": "unknown", "queries": []},
])
async def test_invalid_plan_cannot_fall_back_to_a_text_answer(tmp_path, plan):
    model = PlannedModel(plan)
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client)
        assert run["error_code"] == "grounding_plan" and run["calls"] == 1
        assert not model.answers and "225" not in run["output"]


async def test_future_only_query_fails_before_answer_and_without_memory_job(tmp_path):
    model = PlannedModel({"kind": "business", "queries": [
        {"start": "2999-01-01", "end": "2999-01-02"},
    ]})
    async with chat_app(tmp_path, model) as (client, _, factory):
        run = await ask(client)
        assert run["error_code"] == "grounding_unavailable"
        assert not model.answers
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(AgentMemoryJob)) == 0


@pytest.mark.parametrize("kind", ["general", "clarify"])
async def test_general_and_clarification_keep_streaming_without_business_queries(tmp_path, kind):
    model = PlannedModel({"kind": kind, "queries": []})
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "解释Python生成器" if kind == "general" else "经营怎么样？")
        assert run["status"] == "completed"
        events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
        assert "event: tool" not in events and "event: delta" in events


async def test_planning_consumes_existing_step_budget(tmp_path):
    model = PlannedModel()
    async with chat_app(tmp_path, model) as (client, app, _):
        app.state.agent_runner.settings.agent_max_steps = 1
        run = await ask(client)
        assert run["error_code"] == "step_budget" and run["calls"] == 1
        assert not model.answers


@pytest.mark.parametrize("change", ["source", "store", "requested", "actual"])
async def test_mismatched_tool_result_never_satisfies_the_plan(tmp_path, change):
    from app.agents.assistant.graph import create_graph
    from app.agents.registry import capabilities

    model = PlannedModel()
    skills, tools = capabilities()
    execute = tools.execute

    async def corrupt(call, storage, context):
        result = await execute(call, storage, context)
        if call.name == "store_overview":
            key, value = {
                "source": ("source", "history"), "store": ("store_id", 2),
                "requested": ("requested_range", {"start": "2026-07-01", "end": "2026-07-02"}),
                "actual": ("range", {"start": "2026-07-01", "end": "2026-07-02"}),
            }[change]
            result[key] = value
        return result

    tools.execute = corrupt
    async with chat_app(tmp_path, model) as (client, app, _):
        runner = app.state.agent_runner
        runner.graph = create_graph(model, runner.storage, runner.settings,
                                    agent_capabilities=(skills, tools))
        run = await ask(client)
        assert run["error_code"] == "grounding_unavailable"
        assert not model.answers


async def test_all_planned_periods_are_required_and_disabled_tools_stay_disabled(tmp_path):
    from app.agents.assistant.graph import create_graph
    from app.agents.registry import AgentDefinition, capabilities

    model = PlannedModel({"kind": "business", "queries": [
        {"start": "2026-07-10", "end": "2026-07-11"},
        {"start": "2999-01-01", "end": "2999-01-02"},
    ]})
    async with chat_app(tmp_path, model) as (client, app, _):
        run = await ask(client)
        assert run["error_code"] == "grounding_unavailable" and not model.answers
        events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
        assert events.count("event: grounding") == 1
        runner = app.state.agent_runner
        runner.graph = create_graph(model, runner.storage, runner.settings,
                                    agent_capabilities=capabilities(AgentDefinition("restricted", (), ())))
        run = await ask(client)
        assert run["error_code"] == "grounding_unavailable" and not model.answers
        events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
        assert "event: grounding" not in events and '"name": "unauthorized"' in events


@pytest.mark.parametrize("stage", ["plan", "query"])
@pytest.mark.parametrize("action", ["stop", "reset", "deactivate"])
async def test_planning_and_automatic_query_fence_late_results(tmp_path, stage, action):
    from app.agents.assistant.graph import create_graph
    from app.agents.registry import capabilities

    entered, release = asyncio.Event(), asyncio.Event()

    async def barrier():
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()  # Simulate a provider/tool that returns despite cancellation.

    class Paused(PlannedModel):
        async def stream_plan(self, messages, schemas):
            if stage == "plan":
                await barrier()
            async for chunk in super().stream_plan(messages, schemas):
                yield chunk

    model = Paused()
    skills, tools = capabilities()
    execute = tools.execute

    async def paused_query(call, storage, context):
        result = await execute(call, storage, context)
        if call.name == "store_overview" and stage == "query":
            await barrier()
        return result

    tools.execute = paused_query
    async with chat_app(tmp_path, model) as (client, app, factory):
        runner = app.state.agent_runner
        runner.graph = create_graph(model, runner.storage, runner.settings,
                                    agent_capabilities=(skills, tools))
        submitted = (await client.post("/api/agent/1/messages", json={
            "request_id": uuid4().hex, "generation": 0, "content": "查询2026年7月10日至11日经营数据",
        })).json()
        await asyncio.wait_for(entered.wait(), 10)
        worker = runner.runs[submitted["id"]]
        if action == "stop":
            assert (await client.post(f'/api/agent/1/runs/{submitted["id"]}/stop')).status_code == 200
        elif action == "reset":
            assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
        else:
            assert (await client.patch("/api/admin/stores/1", json={"is_active": False})).status_code == 200
        release.set()
        await asyncio.wait_for(worker, 10)
        assert not model.answers
        if action != "deactivate":
            run = await completed(client, submitted["id"])
            assert run["error_code"] == ("reset" if action == "reset" else "cancelled")
            events = (await client.get(f'/api/agent/1/runs/{submitted["id"]}/events')).text
            assert "event: completed" not in events and "event: grounding" not in events
        else:
            assert (await client.get(f'/api/agent/1/runs/{submitted["id"]}/events')).status_code == 404
        async with factory() as session:
            assert await session.scalar(select(func.count()).select_from(AgentMemoryJob)) == 0


async def test_automatic_queries_respect_tool_budget_before_execution(tmp_path):
    model = PlannedModel()
    async with chat_app(tmp_path, model) as (client, app, _):
        app.state.agent_runner.settings.agent_max_tool_calls = 1
        run = await ask(client)
        assert run["error_code"] == "tool_budget" and run["calls"] == 1
        events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
        assert "event: tool" not in events and not model.answers


async def test_actual_transport_plan_triggers_query_without_model_business_tool_call(tmp_path):
    import httpx
    import respx
    from tests.api.test_agent_tools import sse

    plan = {"kind": "business", "queries": [{"start": "2026-07-10", "end": "2026-07-11"}]}
    first = sse(
        {"choices": [{"delta": {"content": "不得发布的历史225欧元"}}]},
        {"choices": [{"delta": {"tool_calls": [{"index": 0, "id": "plan-1", "function": {
            "name": "plan_response", "arguments": json.dumps(plan),
        }}]}, "finish_reason": "tool_calls"}]},
        {"choices": [], "usage": {"prompt_tokens": 12, "completion_tokens": 8}},
    )
    final = sse({"choices": [{"delta": {"content": "本轮台账150欧元"}}]},
                {"choices": [{"delta": {}, "finish_reason": "stop"}]},
                {"choices": [], "usage": {"prompt_tokens": 30, "completion_tokens": 5}})
    with respx.mock() as mock:
        transport = mock.post("https://bailian.test/v1/chat/completions").mock(side_effect=[
            httpx.Response(200, text=first), httpx.Response(200, text=final),
        ])
        async with chat_app(tmp_path, provider()) as (client, _, _):
            await save_day(client, "2026-07-10", 150)
            run = await ask(client, "查询2026年7月10日至11日经营数据")
            assert run["status"] == "completed" and run["calls"] == transport.call_count == 2
            assert run["usage"] == {"prompt_tokens": 42, "completion_tokens": 13}
            assert "225" not in run["output"]
            planning_wire = json.loads(transport.calls[0].request.content)
            assert [t["function"]["name"] for t in planning_wire["tools"]] == ["plan_response"]
            answering_wire = json.loads(transport.calls[1].request.content)
            results = [json.loads(m["content"]) for m in answering_wire["messages"] if m["role"] == "tool"]
            assert results[0]["skill"] == "store-analysis"
            assert results[1]["income_summary"]["daily_ledger_revenue"] == 150
