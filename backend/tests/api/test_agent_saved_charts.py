"""Historical chart follow-ups through authenticated HTTP/SSE and migrated SQLite."""
import json
import asyncio
import re
from uuid import uuid4
import pytest
from app.agents.providers.bailian import ToolCall
from tests.api.test_agent_chat import chat_app, completed
from tests.api.test_agent_chat_charts import trend_query, trend
from tests.api.test_agent_store_query import QueryModel
from tests.api.test_agent_tools import ask, save_day
from tests.api.test_agent_pagination import save_event


class SavedModel(QueryModel):
    async def stream_plan(self, messages, tools):
        question = next(m["content"] for m in reversed(messages) if m["role"] == "user")
        kind = "saved_chart" if "旧图" in question else "query"
        yield ToolCall("plan", "plan_response", json.dumps({"kind": kind, "queries": []}))


@pytest.fixture(autouse=True)
def chart_budget(monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")


async def saved_chart(client):
    message = (await client.get("/api/agent/1/conversation")).json()["messages"][-1]
    return message["id"], message["charts"][0]["chart_id"]


async def test_saved_followup_pages_original_values_and_reprojects_without_business_read(tmp_path):
    model = SavedModel([("store_data_catalog", {}), trend_query(), trend, "历史图已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        await save_day(client, "2026-07-02", 0)
        await save_day(client, "2026-07-03", None, "未统计")
        assert (await ask(client, "画趋势"))["status"] == "completed"
        message_id, chart_id = await saved_chart(client)
        original = (await client.get(f"/api/agent/1/messages/{message_id}/charts/{chart_id}")).json()
        await save_event(client, "2026-07-01", 999, "后来的修改")

        def continuation(m):
            target = m.results[-1]["targets"][0]
            return "store_chart", {"operation": "read_saved", "result_ref": target["result_ref"],
                "cursor": target["next_cursor"], "page_size": 2}

        def reproject(m):
            target = m.results[-1]["targets"][0]
            return "store_chart", {"operation": "create", "result_ref": target["result_ref"],
                "dimension": "day", "series": ["total_revenue"], "type": "line", "title": "旧图再次绘制"}

        model.actions = iter([("store_chart", {"operation": "read_saved", "message_id": message_id,
            "chart_id": chart_id, "series": ["total_revenue"], "page_size": 2}), continuation,
            reproject, "依据旧图原查询时间，首日19，次日0。"])
        run = await ask(client, "追问旧图并再次画图")
        assert run["status"] == "completed", run
        reads = [r for r in model.results if r.get("source") == "saved_chart" and r.get("targets")]
        assert len(reads) == 2
        first, second = [r["targets"][0] for r in reads]
        assert first["source"] == "saved_chart" and first["queried_at"] == original["payload"]["queried_at"]
        assert first["rows"][0]["values"]["total_revenue"]["exact"] == "19"
        assert first["rows"][1]["values"]["total_revenue"]["exact"] == "0"
        assert first["unread_ranges"] == [{"start": 3, "end": 4}]
        assert second["read_ranges"] == [{"start": 1, "end": 4}] and not second["has_more"]
        new_message, new_chart = await saved_chart(client)
        new = (await client.get(f"/api/agent/1/messages/{new_message}/charts/{new_chart}")).json()
        assert new["payload"]["points"] == original["payload"]["points"]
        assert new["payload"]["queried_at"] == original["payload"]["queried_at"]
        assert new["source"]["source"] == "saved_chart"
        assert (await client.get(f"/api/agent/1/messages/{message_id}/charts/{chart_id}")).json() == original
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"name": "store_query"' not in events
        assert '"source": "saved_chart"' in events
        history_context = model.messages[-1]
        assert any(chart_id in m["content"] and str(message_id) in m["content"]
                   for m in history_context if isinstance(m.get("content"), str))


@pytest.mark.parametrize("mutation,expected", [
    ({"message_id": 3}, "saved_chart_not_found"),
    ({"chart_id": "a" * 32}, "saved_chart_not_found"),
    ({"series": ["forged"]}, "invalid_chart_selection"),
    ({"point_start": 4, "point_end": 2}, "invalid_chart_selection"),
    ({"point_end": 5}, "invalid_chart_selection"),
    ({"store_id": 2}, "invalid_tool_arguments"),
    ({"values": [999]}, "invalid_tool_arguments"),
])
async def test_saved_read_rejects_forged_association_selection_and_extra_values(tmp_path, mutation, expected):
    model = SavedModel([("store_data_catalog", {}), trend_query(), trend, "图已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画趋势"))["status"] == "completed"
        message, chart = await saved_chart(client)
        model.actions = iter([("store_chart", {"operation": "read_saved", "message_id": message,
            "chart_id": chart, **mutation}), "不能依据无效图回答。"])
        run = await ask(client, "旧图追问")
        assert model.results[-1]["error"] == expected
        assert run["status"] == "failed" and run["error_code"] == "grounding_unavailable"


async def test_saved_selection_and_invalid_cursor_preserve_read_progress(tmp_path):
    model = SavedModel([("store_data_catalog", {}), trend_query(), trend, "已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画趋势"))["status"] == "completed"
        message, chart = await saved_chart(client)
        captured = {}
        def forged(m):
            captured.update(m.results[-1]["targets"][0])
            return "store_chart", {"operation": "read_saved", "result_ref": captured["result_ref"],
                "cursor": captured["next_cursor"][:-1] + ("a" if captured["next_cursor"][-1] != "a" else "b")}
        def retry(m):
            return "store_chart", {"operation": "read_saved", "result_ref": captured["result_ref"],
                "cursor": captured["next_cursor"], "page_size": 2}
        model.actions = iter([("store_chart", {"operation": "read_saved", "message_id": message,
            "chart_id": chart, "point_start": 2, "point_end": 4, "page_size": 1}), forged, retry, "依据旧图。"])
        run = await ask(client, "旧图选第二至第四点")
        assert run["status"] == "completed", run
        assert model.results[2]["error"] == "invalid_result_reference"
        target = model.results[-1]["targets"][0]
        assert captured["matched_count"] == 4 and captured["selected_count"] == 3
        assert captured["rows"][0]["dimension"] == "2026-07-02"
        assert target["read_ranges"] == [{"start": 1, "end": 3}]
        reference, cursor = captured["result_ref"], captured["next_cursor"]
        model.actions = iter([("store_chart", {"operation": "read_saved", "result_ref": reference,
            "cursor": cursor}), "结束轮次引用不可复用。"])
        next_run = await ask(client, "旧图复用上一轮引用")
        assert model.results[-1]["error"] == "invalid_result_reference"
        assert next_run["status"] == "failed"


async def test_latest_requires_new_business_evidence_and_preserves_old_chart(tmp_path):
    model = SavedModel([("store_data_catalog", {}), trend_query(), trend, "历史已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画趋势"))["status"] == "completed"
        message, chart = await saved_chart(client)
        original = (await client.get(f"/api/agent/1/messages/{message}/charts/{chart}")).json()
        await save_event(client, "2026-07-01", 999, "后来修改")
        # Routing for latest is query; a successful saved read cannot satisfy it.
        model.actions = iter([("store_chart", {"operation": "read_saved", "message_id": message,
            "chart_id": chart}), "这是最新999。"])
        bypass = await ask(client, "查询最新数据")
        assert bypass["status"] == "failed" and bypass["error_code"] == "grounding_unavailable"
        model.actions = iter([("store_data_catalog", {}), trend_query(), trend, "最新查询为999。"])
        latest = await ask(client, "最新数据画图")
        assert latest["status"] == "completed", latest
        new_message, new_chart = await saved_chart(client)
        new = (await client.get(f"/api/agent/1/messages/{new_message}/charts/{new_chart}")).json()
        assert new["payload"]["points"][0]["values"]["total_revenue"]["exact"] == "999"
        assert new["source"].get("source") != "saved_chart"
        assert (await client.get(f"/api/agent/1/messages/{message}/charts/{chart}")).json() == original


@pytest.mark.parametrize("scope", ["store", "account", "reset"])
async def test_saved_read_cannot_cross_store_account_or_reset(tmp_path, scope):
    model = SavedModel([("store_data_catalog", {}), trend_query(), trend, "已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画趋势"))["status"] == "completed"
        message, chart = await saved_chart(client)
        store = 1
        if scope == "store":
            store = 2
        elif scope == "account":
            assert (await client.post("/api/auth/login", json={"username": "user-2", "password": "Password123"})).status_code == 200
        else:
            assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
        model.actions = iter([("store_chart", {"operation": "read_saved", "message_id": message,
            "chart_id": chart}), "无法读取旧图。"])
        generation = (await client.get(f"/api/agent/{store}/conversation")).json()["generation"]
        submitted = await client.post(f"/api/agent/{store}/messages", json={
            "generation": generation, "request_id": uuid4().hex, "content": f"旧图跨范围 {chart}"})
        assert submitted.status_code == 202
        run = await completed(client, submitted.json()["id"], store=store)
        assert model.results[-1]["error"] == "saved_chart_not_found"
        assert run["status"] == "failed"


async def test_saved_pages_respect_cumulative_context_capacity_and_explain_unread(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "24000")
    from tests.api.test_agent_store_query import query
    model = SavedModel([("store_data_catalog", {}), query([{"id": "year", "domain": "daily_ledger",
        "range": {"start": "2025-01-01", "end": "2025-12-31"}, "metrics": ["total_revenue"],
        "group_by": ["day"], "page_size": 2}]), trend, "全年图已保存。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2025-01-01", 19)
        assert (await ask(client, "画全年趋势"))["status"] == "completed"
        message, chart = await saved_chart(client)
        def next_page(m):
            target = m.results[-1]["targets"][0]
            if target.get("error") == "context_capacity":
                return "已解释本轮读取范围，余下未读。"
            return "store_chart", {"operation": "read_saved", "result_ref": target["result_ref"],
                "cursor": target["next_cursor"], "page_size": 200}
        model.actions = iter([("store_chart", {"operation": "read_saved", "message_id": message,
            "chart_id": chart, "page_size": 50}), *[next_page] * 5, "仅依据已读历史点。"])
        run = await ask(client, f"旧图读取全部点 {chart}")
        assert run["status"] == "completed", run
        pages = [r["targets"][0] for r in model.results if r.get("targets")]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        receipts = [json.loads(part.split("\n")[0]) for part in events.split("event: tool\ndata: ")[1:]]
        last = next(r["targets"][0] for r in reversed(receipts) if r.get("source") == "saved_chart")
        assert pages[0]["rows"] and last["error"] == "context_capacity", last
        assert len({p["result_ref"] for p in pages}) == 1
        assert last["has_more"] and last["next_cursor"]
        assert last["unread_ranges"][-1]["end"] == 365
        assert last["read_ranges"][-1]["end"] < 365
        assert all(len(json.dumps(r, ensure_ascii=False)) <= 12000 for r in model.results if r.get("targets"))
        assert "部分完成" in run["output"] and "原查询时间" in run["output"]
        assert "context_budget" not in events and "context_capacity" in events


@pytest.mark.parametrize("action", ["stop", "reset", "logout", "disable"])
async def test_saved_continuation_is_fenced_after_lifecycle_change(tmp_path, monkeypatch, action):
    from httpx import ASGITransport, AsyncClient
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "user-3")
    class Paused(SavedModel):
        async def stream_tools(self, messages, tools):
            receipts = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
            if receipts and receipts[-1].get("source") == "saved_chart":
                self.read.set()
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    await self.release.wait()
            async for chunk in super().stream_tools(messages, tools):
                yield chunk
    model = Paused([("store_data_catalog", {}), trend_query(), trend, "保存。"])
    model.read, model.release = asyncio.Event(), asyncio.Event()
    async with chat_app(tmp_path, model) as (client, app, _):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画趋势"))["status"] == "completed"
        message, chart = await saved_chart(client)
        def continued(m):
            target = m.results[-1]["targets"][0]
            return "store_chart", {"operation": "read_saved", "result_ref": target["result_ref"],
                "cursor": target["next_cursor"]}
        model.actions = iter([("store_chart", {"operation": "read_saved", "message_id": message,
            "chart_id": chart, "page_size": 1}), continued, "迟到历史回答。"])
        task = asyncio.create_task(ask(client, "旧图追问"))
        await asyncio.wait_for(model.read.wait(), 10)
        run_id = (await client.get("/api/agent/1/conversation")).json()["run"]["id"]
        async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver") as owner:
            await owner.post("/api/auth/login", json={"username": "user-3", "password": "Password123"})
            if action == "stop":
                assert (await client.post(f"/api/agent/1/runs/{run_id}/stop")).status_code == 200
            elif action == "reset":
                assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
            elif action == "logout":
                assert (await client.post("/api/auth/logout")).status_code == 204
            else:
                assert (await owner.patch("/api/admin/users/1", json={"is_active": False})).status_code == 200
            model.release.set()
            await asyncio.gather(task, return_exceptions=True)
            if action == "disable":
                assert (await owner.patch("/api/admin/users/1", json={"is_active": True})).status_code == 200
        if action in ("logout", "disable"):
            assert (await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})).status_code == 200
        history = (await client.get("/api/agent/1/conversation")).json()
        assert len(history["messages"]) == (0 if action == "reset" else 5)
        assert all("迟到历史回答" not in m["content"] for m in history["messages"])
        if action != "reset":
            assert history["run"]["status"] == "failed"


@pytest.mark.parametrize("kind", ["grouped_bar", "stacked_bar", "horizontal_bar"])
async def test_saved_extensions_select_series_and_reproject_original_trusted_shape(tmp_path, kind):
    from tests.api.test_agent_chart_groups import chart, seed_composition, composition_query
    from tests.api.test_agent_store_query import query
    if kind == "stacked_bar":
        request = composition_query()
        creation = chart(type=kind, dimension="month", series=["amount"], series_by="category")
    elif kind == "grouped_bar":
        request = query([{"id": "months", "domain": "monthly_income",
            "range": {"start": "2026-07-01", "end": "2026-08-31"},
            "metrics": ["daily_ledger_revenue", "confirmed_settlement_income"], "group_by": ["month"]}])
        creation = chart(type=kind, dimension="month", series=["daily_ledger_revenue", "confirmed_settlement_income"])
    else:
        request = query([{"id": "rank", "domain": "daily_ledger", "range": {"all_history": True},
            "fields": ["date", "daily_revenue"], "order_by": [{"field": "daily_revenue", "direction": "desc"}], "top_n": 3}])
        creation = chart(type=kind, dimension="date", series=["daily_revenue"])
    model = SavedModel([("store_data_catalog", {}), request, creation, "保存扩展图。"])
    async with chat_app(tmp_path, model) as (client, _, factory):
        if kind == "stacked_bar":
            await seed_composition(client)
        else:
            await save_day(client, "2026-07-01", 19)
            await save_day(client, "2026-07-02", 100)
        assert (await ask(client, "画扩展图"))["status"] == "completed"
        message, chart_id = await saved_chart(client)
        original = (await client.get(f"/api/agent/1/messages/{message}/charts/{chart_id}")).json()["payload"]
        chosen = original["series"][0]["key"]
        def create(m):
            return "store_chart", {"operation": "create", "result_ref": m.results[-1]["targets"][0]["result_ref"],
                "dimension": original["dimension"], "series": [chosen], "type": kind, "title": "选定历史系列"}
        model.actions = iter([("store_chart", {"operation": "read_saved", "message_id": message,
            "chart_id": chart_id, "series": [chosen], "point_end": 2}), create, "依旧图选定系列前两点。"])
        # Fault all business SELECTs: saved reading/projection and viewing still work.
        from sqlalchemy import event
        def forbid_business(conn, cursor, statement, parameters, context, executemany):
            if statement.lstrip().upper().startswith("SELECT") and re.search(
                r"\b(?:FROM|JOIN)\s+(?:store_daily_records|daily_income_items|settlement_records)\b", statement, re.I):
                raise AssertionError("Saved chart must not query business data")
        engine = factory.kw["bind"].sync_engine
        event.listen(engine, "before_cursor_execute", forbid_business)
        try:
            run = await ask(client, "旧图选择系列再次绘图")
            assert run["status"] == "completed", run
            new_message, new_chart = await saved_chart(client)
            new = (await client.get(f"/api/agent/1/messages/{new_message}/charts/{new_chart}")).json()["payload"]
        finally:
            event.remove(engine, "before_cursor_execute", forbid_business)
        assert new["type"] == kind and new["queried_at"] == original["queried_at"]
        assert len(new["series"]) == 1 and len(new["points"]) == 2
        assert [p["dimension"] for p in new["points"]] == [p["dimension"] for p in original["points"][:2]]
        assert [p["values"][chosen] for p in new["points"]] == [p["values"][chosen] for p in original["points"][:2]]


async def test_out_of_context_old_chart_asks_before_latest_query_and_keeps_original(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "24000")
    from tests.browser.saved_chart_server import BrowserSavedModel
    model = BrowserSavedModel()
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        for index in range(12):
            assert (await ask(client, f"画趋势 {index}"))["status"] == "completed"
        message, chart_id = await saved_chart(client)
        original = (await client.get(f"/api/agent/1/messages/{message}/charts/{chart_id}")).json()
        run = await ask(client, "追问旧图")
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        assert "这张旧图已超出当前上下文，是否重新查询最新数据？" in run["output"]
        assert "历史图来源：saved_chart" not in run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"name": "store_query"' not in events and '"name": "store_chart"' not in events
        assert (await client.get("/api/agent/1/conversation")).json()["messages"][-1]["charts"] == []
        await save_event(client, "2026-07-01", 999, "确认前台账已更新")
        confirmed = await ask(client, "确认重新查询最新数据并生成新图")
        assert confirmed["status"] == "completed", confirmed
        new_message, new_chart = await saved_chart(client)
        new = (await client.get(f"/api/agent/1/messages/{new_message}/charts/{new_chart}")).json()
        assert new["payload"]["points"][0]["values"]["total_revenue"]["exact"] == "999"
        assert new["source"].get("source") != "saved_chart"
        assert (await client.get(f"/api/agent/1/messages/{message}/charts/{chart_id}")).json() == original


async def test_advertised_chart_schema_preserves_business_title_and_runtime_accepts_it(tmp_path):
    class SchemaModel(QueryModel):
        async def stream_tools(self, messages, tools):
            parameters = next(t["function"]["parameters"] for t in tools if t["function"]["name"] == "store_chart")
            assert parameters["type"] == "object" and parameters["additionalProperties"] is False
            assert parameters["properties"]["title"]["type"] == "string"
            assert parameters["properties"]["title"]["maxLength"] == 80
            async for chunk in super().stream_tools(messages, tools):
                yield chunk
    model = SchemaModel([("store_data_catalog", {}), trend_query(), trend, "按广告契约创建成功。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 19)
        assert (await ask(client, "画趋势"))["status"] == "completed"
        message, chart_id = await saved_chart(client)
        assert (await client.get(f"/api/agent/1/messages/{message}/charts/{chart_id}")).json()["payload"]["title"] == "逐日营业额"
