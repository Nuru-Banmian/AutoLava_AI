"""Chart follow-ups query fresh evidence; saved charts remain viewable."""
import json
import pytest
from app.agents.registry import capabilities
from app.agents.providers.bailian import ToolCall
from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_chat_charts import trend_query, trend
from tests.api.test_agent_store_query import QueryModel
from tests.api.test_agent_tools import ask, save_day
from tests.api.test_agent_pagination import save_event

class SavedModel(QueryModel):
    async def stream_plan(self, messages, tools):
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        kind = "saved_chart" if "旧图" in question else "query"
        yield ToolCall("plan", "plan_response", json.dumps({"kind": kind, "queries": []}))

async def saved_chart(client):
    message = (await client.get("/api/agent/1/conversation")).json()["messages"][-1]
    return message["id"], message["charts"][0]["chart_id"]

def test_chart_and_plan_schemas_only_offer_fresh_sources():
    from app.agents.assistant.grounding import PLAN_SCHEMA
    _, tools = capabilities()
    schema = next(t["function"]["parameters"] for t in tools.schemas if t["function"]["name"] == "store_chart")
    assert schema["properties"]["operation"].get("const") == "create"
    assert "message_id" not in schema["properties"]
    assert PLAN_SCHEMA[0]["function"]["parameters"]["properties"]["kind"]["enum"] == ["general", "clarify", "query"]

@pytest.mark.parametrize("new_chart", [False, True])
async def test_old_chart_followup_uses_latest_values_and_preserves_original(tmp_path, new_chart):
    model = SavedModel([("store_data_catalog", {}), trend_query(), trend, "图已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画2026年7月每日台账营业额折线图"))["status"] == "completed"
        message, chart = await saved_chart(client)
        url = f"/api/agent/1/messages/{message}/charts/{chart}"
        original = (await client.get(url)).json()
        await save_event(client, "2026-07-01", 999, "后来修改")
        actions = [("store_data_catalog", {}), trend_query()]
        if new_chart:
            actions.append(trend)
        model.actions = iter([*actions, "首日营业额999。"])
        run = await ask(client, "旧图首日是多少？" + ("重新画图" if new_chart else "不用图"))
        assert run["status"] == "completed", run
        assert "999" in run["output"] and "最新数据" in run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"name": "store_query"' in events
        assert '"source": "saved_chart"' not in events
        assert (await client.get(url)).json() == original
        history = model.messages[-1]
        assert not any("图已保存。" in (m.get("content") or "") for m in history)
        assert any("此前图表范围" in (m.get("content") or "") for m in history)
        if new_chart:
            new_message, new_id = await saved_chart(client)
            snapshot = (await client.get(f"/api/agent/1/messages/{new_message}/charts/{new_id}")).json()
            assert snapshot["payload"]["points"][0]["values"]["total_revenue"]["exact"] == "999"

async def test_legacy_snapshot_tool_cannot_ground_an_answer(tmp_path):
    model = SavedModel([("store_chart", {"operation": "read_saved", "message_id": 1, "chart_id": "a" * 32}), "旧图值19。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "旧图2026年7月营业额是多少？")
        assert model.results[-1]["error"] == "invalid_tool_arguments"
        assert run["status"] == "failed" and run["error_code"] == "grounding_unavailable"
        assert "19" not in run["output"]

async def test_missing_chart_context_asks_for_required_information(tmp_path):
    model = QueryModel(["请补充日期范围和指标，我会查询最新数据。"])
    async def clarify(messages, tools):
        yield ToolCall("plan", "plan_response", '{"kind":"clarify","queries":[]}')
    model.stream_plan = clarify
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "刚才图里那个是多少？")
        assert run["status"] == "completed" and "日期范围和指标" in run["output"]
        assert not any(r.get("targets") for r in model.results)

@pytest.mark.parametrize("scope", ["store", "account", "reset"])
async def test_viewing_saved_chart_remains_scope_fenced(tmp_path, scope):
    model = QueryModel([("store_data_catalog", {}), trend_query(), trend, "图已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画趋势"))["status"] == "completed"
        message, chart = await saved_chart(client)
        store = 1
        if scope == "store":
            store = 2
        elif scope == "account":
            assert (await client.post("/api/auth/login", json={"username":"user-2", "password":"Password123"})).status_code == 200
        else:
            assert (await client.post("/api/agent/1/conversation/reset", json={"generation":0})).status_code == 200
        assert (await client.get(f"/api/agent/{store}/messages/{message}/charts/{chart}")).status_code == 404
