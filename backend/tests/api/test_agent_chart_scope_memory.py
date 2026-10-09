"""Chart restoration keeps current store grants and effective SQLite memory."""
import asyncio
import json
from uuid import uuid4

from sqlalchemy import delete

from app.models.agent import AgentMemory
from app.models.identity import StoreMember
from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_chat_charts import trend, trend_query
from tests.api.test_agent_store_query import QueryModel
from tests.api.test_agent_tools import ask, background, save_day
from tests.api.test_agent_vectors import Embedding, configured, wait_status  # noqa: F401


async def test_failed_memory_read_with_missing_range_clarifies_without_business_query(tmp_path):
    from app.agents.assistant.graph import create_graph
    from app.agents.providers.bailian import ToolCall
    class MissingMemory:
        async def retrieve(self, scope, run_id):
            return {"status": "unavailable", "items": []}
    class Clarify(QueryModel):
        async def stream_plan(self, messages, tools):
            snapshot = background(messages)
            assert snapshot["memories"] == [] and snapshot["memory_retrieval"] == "unavailable"
            yield ToolCall("plan", "plan_response", '{"kind":"clarify","queries":[]}')
        async def stream_tools(self, messages, tools):
            assert "缺必要信息则追问" in messages[0]["content"]
            yield "长期记忆当前不可用，请补充要查询的日期范围。"
    # Planning receives a compact router prompt; assert its observable snapshot.
    model = Clarify([])
    async with chat_app(tmp_path, model) as (client, app, _):
        runner = app.state.agent_runner
        runner.graph = create_graph(model, runner.storage, runner.settings, memory_index=MissingMemory())
        run = await ask(client, "按我长期记忆中保存的日期范围查询台账营业额")
        assert run["status"] == "completed" and "请补充" in run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"name": "store_query"' not in events
        assert "本轮未参考长期记忆" in run["output"]


async def test_chart_turn_retains_private_effective_memory_after_reset(tmp_path, monkeypatch, configured):  # noqa: F811
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    model = QueryModel([("store_data_catalog", {}), trend_query(), trend, "已保留记忆并保存图表。"])
    async with chat_app(tmp_path, model, embedding=Embedding()) as (client, app, sessions):
        async with sessions() as session:
            for user, store, status, text in [(1, 1, "active", "分析先说明未统计覆盖"), (1, 1, "pending_confirmation", "待确认背景"), (2, 1, "active", "另一管理员私有"), (1, 2, "active", "另一门店私有")]:
                session.add(AgentMemory(id=uuid4().hex, user_id=user, store_id=store, content=text, category="preference", status=status))
            await session.commit()
        app.state.agent_runner.index.start()
        await wait_status(client, "available")
        before = (await client.get("/api/agent/1/memories")).json()
        assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
        assert (await client.get("/api/agent/1/memories")).json() == before
        await save_day(client, "2026-07-01", 19)
        run = await ask(client, "按记忆画营业额趋势")
        assert run["status"] == "completed", run
        context = background(model.messages[-1])
        assert [m["content"] for m in context["memories"]] == ["分析先说明未统计覆盖"]
        assert context["memory_retrieval"] == "available"
        assert "本轮未参考长期记忆" not in run["output"]
        assert len((await client.get("/api/agent/1/conversation")).json()["messages"][-1]["charts"]) == 1


async def test_removed_admin_store_grant_fences_prepared_chart_and_saved_reads(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    class Paused(QueryModel):
        def __init__(self):
            super().__init__([("store_data_catalog", {}), trend_query(), trend, "已保存首图。", ("store_data_catalog", {}), trend_query(), trend, "撤权后不发布。"])
            self.prepared = asyncio.Event()
            self.release = asyncio.Event()
            self.count = 0

        async def stream_tools(self, messages, tools):
            receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if receipts and receipts[-1].get("status") == "prepared":
                self.count += 1
                if self.count == 2:
                    self.prepared.set()
                    try:
                        await self.release.wait()
                    except asyncio.CancelledError:
                        await self.release.wait()
            async for item in super().stream_tools(messages, tools):
                yield item
    model = Paused()
    async with chat_app(tmp_path, model) as (client, app, sessions):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "首图"))["status"] == "completed"
        old = (await client.get("/api/agent/1/conversation")).json()
        message = old["messages"][-1]
        url = f"/api/agent/1/messages/{message['id']}/charts/{message['charts'][0]['chart_id']}"
        assert (await client.get(url)).status_code == 200
        second = await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "第二张图"})
        worker = app.state.agent_runner.runs[second.json()["id"]]
        await asyncio.wait_for(model.prepared.wait(), 10)
        async with sessions() as session:
            await session.execute(delete(StoreMember).where(StoreMember.user_id == 1, StoreMember.store_id == 1))
            await session.commit()
        assert (await client.get(url)).status_code == 404
        model.release.set()
        await asyncio.wait_for(worker, 10)
        async with sessions() as session:
            session.add(StoreMember(user_id=1, store_id=1))
            await session.commit()
        final = (await client.get("/api/agent/1/conversation")).json()
        assert final["run"]["status"] == "failed" and final["run"]["error_code"] == "access_revoked"
        assert len([m for m in final["messages"] if m["charts"]]) == 1
        assert (await client.get(url)).status_code == 200
