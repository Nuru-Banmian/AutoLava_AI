"""Trusted chart snapshots observed through authenticated chat, history and SSE."""
import json
import asyncio
import pytest

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_pagination import latest_batch
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import ask, save_day


@pytest.fixture(autouse=True)
def chart_budget(monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")


def trend(model):
    return "store_chart", {"operation": "create", "result_ref": latest_batch(model)["targets"][0]["result_ref"],
                           "block": "main", "dimension": "day", "series": ["total_revenue"],
                           "type": "line", "title": "逐日营业额"}


def trend_query(page_size=50):
    return query([{"id": "trend", "domain": "daily_ledger",
                  "range": {"start": "2026-07-01", "end": "2026-07-04"},
                  "metrics": ["total_revenue"], "group_by": ["day"], "page_size": page_size}])


async def test_chart_is_saved_with_message_and_replayed_as_descriptor(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    model = QueryModel([("store_data_catalog", {}), trend_query(), trend, "零额保留，未统计与未录入断线。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        await save_day(client, "2026-07-02", 0)
        await save_day(client, "2026-07-03", None, "未统计")
        run = await ask(client, "画四天营业额趋势")
        assert run["status"] == "completed", run
        prepared = model.results[-1]
        assert prepared["status"] == "prepared", prepared
        history = (await client.get("/api/agent/1/conversation")).json()
        message = history["messages"][-1]
        assert all(m["charts"] == [] for m in history["messages"][:-1])
        assert len(message["charts"]) == 1
        descriptor = message["charts"][0]
        assert descriptor["chart_id"] == prepared["charts"][0]["chart_id"]
        assert "points" not in json.dumps(history)
        chart = (await client.get(f"/api/agent/1/messages/4/charts/{descriptor['chart_id']}")).json()
        assert chart["message_id"] == message["id"]
        points = chart["payload"]["points"]
        assert [p["values"]["total_revenue"]["exact"] for p in points] == ["19", "0", None, None]
        assert [p["state"] for p in points] == ["营业", "营业", "未统计", "未录入"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        complete = events.split("event: completed\ndata: ")[1].split("\n")[0]
        receipt = json.loads(complete)
        assert receipt["message_id"] == message["id"] and receipt["charts"] == message["charts"]
        assert "points" not in events
        event_ids = [int(line[4:]) for line in events.splitlines() if line.startswith("id: ")]
        replay = await client.get(f"/api/agent/1/runs/{run['id']}/events", headers={"Last-Event-ID": str(event_ids[-2])})
        assert replay.text.count("event: completed") == 1 and "points" not in replay.text
        done = await client.get(f"/api/agent/1/runs/{run['id']}/events", headers={"Last-Event-ID": str(event_ids[-1])})
        assert done.text == ""
        assert (await client.get(f"/api/agent/2/messages/4/charts/{descriptor['chart_id']}")).status_code == 404
        assert (await client.get("/api/agent/1/messages/4/charts/unknown")).status_code == 404
        reset = await client.post("/api/agent/1/conversation/reset", json={"generation": history["generation"]})
        assert reset.status_code == 200
        assert (await client.get(f"/api/agent/1/messages/4/charts/{descriptor['chart_id']}")).status_code == 404


@pytest.mark.parametrize("mutation,error", [
    ({"result_ref": "a" * 32}, "invalid_chart_source"),
    ({"series": ["total_wash_count"]}, "invalid_chart_source"),
    ({"dimension": "month"}, "invalid_chart_source"),
    ({"values": [123]}, "invalid_tool_arguments"),
])
async def test_chart_rejects_model_values_and_forged_source(tmp_path, mutation, error):
    def invalid(model):
        name, args = trend(model)
        return name, {**args, **mutation}
    model = QueryModel([("store_data_catalog", {}), trend_query(), invalid, "图表请求未完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 5)
        run = await ask(client, "画趋势")
        assert run["status"] == "completed", run
        assert model.results[-1]["error"] == error
        assert "图表请求未生成" in run["output"]
        assert (await client.get("/api/agent/1/conversation")).json()["messages"][-1]["charts"] == []


async def test_paginated_query_chart_uses_complete_snapshot_not_current_page(tmp_path):
    model = QueryModel([("store_data_catalog", {}), trend_query(2), trend, "完整四日趋势已准备，明细只读了两行。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 5)
        run = await ask(client, "完整趋势图")
        assert run["status"] == "completed", run
        assert model.results[-1]["status"] == "prepared"
        charts = (await client.get("/api/agent/1/conversation")).json()["messages"][-1]["charts"]
        assert len(charts) == 1 and charts[0]["point_count"] == 4
        snapshot = (await client.get(f"/api/agent/1/messages/4/charts/{charts[0]['chart_id']}")).json()
        assert len(snapshot["payload"]["points"]) == 4
        assert latest_batch(model)["targets"][0]["read_range"] == {"start": 1, "end": 2}
        assert "已读取 2/4 行" in run["output"]


async def test_snapshot_survives_ledger_edits_and_new_application(tmp_path):
    from httpx import ASGITransport, AsyncClient
    from app.main import create_app
    from app.core.database import get_session
    from tests.api.test_agent_chat import NoWeather
    from tests.api.test_agent_pagination import save_event
    model = QueryModel([("store_data_catalog", {}), trend_query(), trend, "历史图已保存。"])
    async with chat_app(tmp_path, model) as (client, app, factory):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画趋势"))["status"] == "completed"
        history = (await client.get("/api/agent/1/conversation")).json()
        chart_id = history["messages"][-1]["charts"][0]["chart_id"]
        original = (await client.get(f"/api/agent/1/messages/4/charts/{chart_id}")).json()
        await save_event(client, "2026-07-01", 999, "新值")
        await app.state.agent_runner.close()
        restarted = create_app(session_factory=factory, agent_model=model, weather_service=NoWeather())
        restarted.dependency_overrides[get_session] = app.dependency_overrides[get_session]
        try:
            async with AsyncClient(transport=ASGITransport(restarted), base_url="http://testserver",
                                   cookies=client.cookies) as reader:
                await restarted.state.agent_runner.storage.recover()
                assert (await reader.get(f"/api/agent/1/messages/4/charts/{chart_id}")).json() == original
                assert (await reader.get("/api/agent/1/conversation")).json() == history
                await reader.post("/api/auth/login", json={"username": "user-2", "password": "Password123"})
                assert (await reader.get(f"/api/agent/1/messages/4/charts/{chart_id}")).status_code == 404
        finally:
            await restarted.state.agent_runner.close()


async def test_completion_write_failure_rolls_back_chart_and_message(tmp_path):
    from sqlalchemy import event
    model = QueryModel([("store_data_catalog", {}), trend_query(), trend, "准备好了。"])
    async with chat_app(tmp_path, model) as (client, _, factory):
        await save_day(client, "2026-07-01", 1)
        engine = factory.kw["bind"].sync_engine
        def fail_insert(conn, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO agent_charts"):
                raise RuntimeError("controlled chart persistence failure")
        event.listen(engine, "before_cursor_execute", fail_insert)
        try:
            run = await ask(client, "画趋势")
        finally:
            event.remove(engine, "before_cursor_execute", fail_insert)
        assert run["status"] == "failed" and run["error_code"] == "internal_error"
        history = (await client.get("/api/agent/1/conversation")).json()
        assert [m["role"] for m in history["messages"]] == ["user", "assistant", "user"]
        chart_id = model.results[-1]["charts"][0]["chart_id"]
        assert (await client.get(f"/api/agent/1/messages/4/charts/{chart_id}")).status_code == 404
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert "event: completed" not in events and "event: failed" in events


@pytest.mark.parametrize("action", ["stop", "reset", "logout", "disable"])
async def test_late_prepared_chart_cannot_publish_after_lifecycle_change(tmp_path, monkeypatch, action):
    from httpx import ASGITransport, AsyncClient
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "user-3")
    class Paused(QueryModel):
        def __init__(self):
            super().__init__([("store_data_catalog", {}), trend_query(), trend, "迟到文字"])
            self.prepared = asyncio.Event()
            self.release = asyncio.Event()
        async def stream_tools(self, messages, tools):
            receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if receipts and receipts[-1].get("status") == "prepared":
                self.receipt = receipts[-1]
                self.prepared.set()
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    await self.release.wait()
            async for item in super().stream_tools(messages, tools):
                yield item
    model = Paused()
    async with chat_app(tmp_path, model) as (client, app, _):
        await save_day(client, "2026-07-01", 1)
        task = asyncio.create_task(ask(client, "画趋势"))
        await asyncio.wait_for(model.prepared.wait(), 10)
        run_id = (await client.get("/api/agent/1/conversation")).json()["run"]["id"]
        if action == "stop":
            assert (await client.post(f"/api/agent/1/runs/{run_id}/stop")).status_code == 200
        elif action == "reset":
            assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
        elif action == "logout":
            assert (await client.post("/api/auth/logout")).status_code == 204
        else:
            async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver") as owner:
                await owner.post("/api/auth/login", json={"username": "user-3", "password": "Password123"})
                assert (await owner.patch("/api/admin/users/1", json={"is_active": False})).status_code == 200
        model.release.set()
        # Revoked HTTP callers are expected to lose polling access.
        result = await asyncio.gather(task, return_exceptions=True)
        if action in ("stop", "reset"):
            assert result[0]["status"] == "failed"
        if action == "disable":
            async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver", cookies=owner.cookies) as owner_reader:
                assert (await owner_reader.patch("/api/admin/users/1", json={"is_active": True})).status_code == 200
        if action in ("logout", "disable"):
            assert (await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})).status_code == 200
        chart_id = model.receipt["charts"][0]["chart_id"]
        assert (await client.get(f"/api/agent/1/messages/4/charts/{chart_id}")).status_code == 404
        history = (await client.get("/api/agent/1/conversation")).json()
        assert all(not m["charts"] for m in history["messages"])
        assert len(history["messages"]) == (0 if action == "reset" else 3)


async def test_chart_count_rejects_new_draft_and_keeps_first_eight(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_MAX_TOOL_CALLS", "16")
    monkeypatch.setenv("AUTOLAVA_AGENT_MAX_STEPS", "12")
    from app.agents.providers.bailian import ToolCall
    from uuid import uuid4
    class ManyCharts(QueryModel):
        async def stream_tools(self, messages, tools):
            receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if receipts and "targets" in receipts[-1]:
                self.results = receipts
                name, args = trend(self)
                for _ in range(9):
                    yield ToolCall(uuid4().hex, name, json.dumps(args))
            else:
                async for item in super().stream_tools(messages, tools):
                    yield item
    model = ManyCharts([("store_data_catalog", {}), trend_query(), "有一张超量图未生成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 1)
        run = await ask(client, "准备九张趋势")
        assert run["status"] == "completed", run
        assert model.results[-1]["error"] == "chart_capacity_exceeded"
        charts = (await client.get("/api/agent/1/conversation")).json()["messages"][-1]["charts"]
        assert len(charts) == len({c["chart_id"] for c in charts}) == 8


@pytest.mark.parametrize("series,error", [
    (["total_revenue", "total_wash_count"], "chart_mixed_units"),
    (["total_revenue", "average_ledger_revenue", "average_revenue_per_car", "min_revenue", "max_revenue"],
     "chart_capacity_exceeded"),
])
async def test_mixed_units_and_single_snapshot_byte_limit_are_explicit(tmp_path, series, error):
    def chart(model):
        name, args = trend(model)
        return name, {**args, "series": series}
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "large", "domain": "daily_ledger", "range": {"start": "2025-01-01", "end": "2025-12-31"},
        "metrics": series, "group_by": ["day"], "page_size": 5,
    }]), chart, "图表超出允许条件，未生成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2025-01-01", 1)
        run = await ask(client, "按原始粒度画图")
        assert run["status"] == "completed", run
        assert model.results[-1]["error"] == error
        assert (await client.get("/api/agent/1/conversation")).json()["messages"][-1]["charts"] == []


async def test_message_byte_limit_rejects_next_draft_before_count_limit(tmp_path, monkeypatch):
    from app.agents.providers.bailian import ToolCall
    from uuid import uuid4
    monkeypatch.setenv("AUTOLAVA_AGENT_MAX_TOOL_CALLS", "16")
    class ByteCharts(QueryModel):
        async def stream_tools(self, messages, tools):
            receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if receipts and "targets" in receipts[-1]:
                self.results = receipts
                name, args = trend(self)
                args["series"] = ["total_revenue", "min_revenue", "max_revenue"]
                for _ in range(8):
                    yield ToolCall(uuid4().hex, name, json.dumps(args))
            else:
                async for item in super().stream_tools(messages, tools):
                    yield item
    model = ByteCharts([("store_data_catalog", {}), query([{
        "id": "large", "domain": "daily_ledger", "range": {"start": "2025-01-01", "end": "2025-10-27"},
        "metrics": ["total_revenue", "min_revenue", "max_revenue"], "group_by": ["day"], "page_size": 5,
    }]), "保留已经准备的图，新增图超量拒绝。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2025-01-01", 1)
        run = await ask(client, "创建多张300点图")
        assert run["status"] == "completed", run
        prepared = [r for r in model.results if r.get("status") == "prepared"]
        assert 1 <= len(prepared) < 8
        assert model.results[-1]["error"] == "chart_capacity_exceeded"
        charts = (await client.get("/api/agent/1/conversation")).json()["messages"][-1]["charts"]
        assert [c["chart_id"] for c in charts] == [r["charts"][0]["chart_id"] for r in prepared]
        snapshots = [(await client.get(f"/api/agent/1/messages/4/charts/{c['chart_id']}")).json() for c in charts]
        sizes = [len(json.dumps(s, ensure_ascii=False).encode("utf-8")) for s in snapshots]
        assert all(size <= 96 * 1024 for size in sizes)
        assert sum(sizes) <= 512 * 1024 < sum(sizes) + sizes[0]


async def test_reset_cascades_old_snapshots_and_new_run_rejects_old_result_ref(tmp_path):
    old = {}
    def keep_ref(model):
        name, args = trend(model)
        old.update(args)
        return name, args
    def use_old_ref(model):
        return "store_chart", old
    model = QueryModel([("store_data_catalog", {}), trend_query(), keep_ref, "首图已保存。",
                        ("store_data_catalog", {}), trend_query(), use_old_ref, trend, "新的图已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 7)
        assert (await ask(client, "首图"))["status"] == "completed"
        first = (await client.get("/api/agent/1/conversation")).json()
        old_id = first["messages"][-1]["charts"][0]["chart_id"]
        await client.post("/api/agent/1/conversation/reset", json={"generation": first["generation"]})
        assert (await ask(client, "新图"))["status"] == "completed"
        second = (await client.get("/api/agent/1/conversation")).json()
        message = second["messages"][-1]
        assert len(message["charts"]) == 1 and message["charts"][0]["chart_id"] != old_id
        assert any(r.get("error") == "invalid_chart_source" for r in model.results)
        assert (await client.get(f"/api/agent/1/messages/{message['id']}/charts/{old_id}")).status_code == 404
        assert (await client.get(f"/api/agent/1/messages/{message['id']}/charts/{message['charts'][0]['chart_id']}")).status_code == 200


async def test_chart_uses_snapshot_without_any_business_reread(tmp_path):
    from sqlalchemy import event
    def chart(model):
        event.listen(engine, "before_cursor_execute", deny_ledger)
        return trend(model)
    def deny_ledger(conn, cursor, statement, parameters, context, executemany):
        if "store_daily_records" in statement:
            raise RuntimeError("Chart must reuse its query snapshot")
    model = QueryModel([("store_data_catalog", {}), trend_query(), chart, "同次快照图已保存。"])
    async with chat_app(tmp_path, model) as (client, _, factory):
        engine = factory.kw["bind"].sync_engine
        await save_day(client, "2026-07-01", 17)
        try:
            run = await ask(client, "画同次查询图")
        finally:
            event.remove(engine, "before_cursor_execute", deny_ledger)
        assert run["status"] == "completed", run
        assert model.results[-1]["status"] == "prepared"


@pytest.mark.parametrize("budget", ["step", "output"])
async def test_budget_failure_after_preparation_does_not_publish_chart(tmp_path, monkeypatch, budget):
    if budget == "step":
        monkeypatch.setenv("AUTOLAVA_AGENT_MAX_STEPS", "4")
    else:
        monkeypatch.setenv("AUTOLAVA_AGENT_OUTPUT_CHARS", "1200")
    model = QueryModel([("store_data_catalog", {}), trend_query(), trend, "超长文字" * 800])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 1)
        run = await ask(client, "画图")
        assert run["status"] == "failed" and run["error_code"] == f"{budget}_budget", run
        # prepared tool receipt is observable in persisted SSE even though the chart is unpublished.
        sse = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"name": "store_chart"' in sse and "event: completed" not in sse
        assert all(not m["charts"] for m in (await client.get("/api/agent/1/conversation")).json()["messages"])


async def test_unfinished_period_is_preserved_in_saved_snapshot(tmp_path, monkeypatch):
    from datetime import date
    monkeypatch.setattr("app.agents.tools.store_query.local_today", lambda store: date(2026, 7, 4))
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "current", "domain": "daily_ledger", "range": {"preset": "this_month"},
        "metrics": ["total_revenue"], "group_by": ["day"],
    }]), trend, "本月尚未结束。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 9)
        assert (await ask(client, "本月至今趋势"))["status"] == "completed"
        chart_id = (await client.get("/api/agent/1/conversation")).json()["messages"][-1]["charts"][0]["chart_id"]
        saved = (await client.get(f"/api/agent/1/messages/4/charts/{chart_id}")).json()
        assert saved["payload"]["unfinished"] is True
        assert saved["payload"]["range"] == {"start": "2026-07-01", "end": "2026-07-04"}
