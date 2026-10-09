"""Result pagination capacity acceptance through authenticated HTTP/SSE only."""

from datetime import date, timedelta
import json

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import ask, save_day
from app.agents.providers.bailian import ToolCall


async def test_unread_first_page_is_explicit_in_saved_answer_and_sse(tmp_path):
    model = QueryModel([
        ("store_data_catalog", {}),
        query([{"id": "days", "domain": "daily_ledger", "range": {"all_history": True},
                "fields": ["date", "daily_revenue"]}]),
        "查询结果已整理。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        first = date(2026, 7, 1)
        for offset in range(51):
            await save_day(client, (first + timedelta(days=offset)).isoformat(), 1)
        run = await ask(client, "查询全部历史每日台账")
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        target = model.results[-1]["targets"][0]
        assert len(target["rows"]) == 50
        assert target["matched_count"] == target["selected_count"] == 51
        assert target["has_more"] and target["result_ref"]
        assert "部分完成" in run["output"] and "未读取" in run["output"]
        assert "50/51" in run["output"]
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["content"] == run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"name": "store_query"' in events
        assert "部分完成" in events and "event: completed" in events
        assert "context_budget" not in events


async def test_cumulative_escaped_pages_keep_evidence_and_complete_at_capacity(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "24000")
    event = '完整事件\\"' * 300

    def next_page(model):
        target = model.results[-1]["targets"][0]
        if target.get("error") == "context_capacity":
            return "已整理本轮能够读取的完整事件。"
        assert target["has_more"], target
        return ("store_query", {"continuations": [{"result_ref": target["result_ref"],
                "cursor": target["next_cursor"], "page_size": 200}]})

    class BoundedModel(QueryModel):
        async def stream_tools(self, messages, schemas):
            # The public model request includes nested escaping and all schemas.
            payload = {"messages": messages, "tools": schemas}
            assert len(json.dumps(payload, ensure_ascii=False)) <= 24000 - 2000
            async for chunk in super().stream_tools(messages, schemas):
                yield chunk

    model = BoundedModel([
        ("store_data_catalog", {}),
        query([{"id": "events", "domain": "daily_ledger", "range": {"all_history": True},
                "fields": ["date", "activity"]}]),
        *[next_page] * 4,
        "已整理本轮能够读取的完整事件。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day in range(1, 11):
            saved = await client.put(f"/api/ledger/1/2026-07-{day:02}", json={
                "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
                "is_open": "营业", "daily_revenue": day, "activity": event})
            assert saved.status_code == 201, saved.text
        run = await ask(client, "读取全部每日台账完整事件，可按页继续")
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        pages = [result["targets"][0] for result in model.results if "targets" in result]
        first, last = pages[0], pages[-1]
        assert first["rows"] and first["has_more"]
        assert last["error"] == "context_capacity", pages
        assert all(page["result_ref"] == first["result_ref"] for page in pages)
        assert last["matched_count"] == last["selected_count"] == 10
        assert last["has_more"] and last["next_cursor"]
        assert last["read_range"]["end"] < 10
        assert last["unread_range"]["start"] == last["read_range"]["end"] + 1
        assert last["unread_range"]["end"] == 10
        obtained = [row for page in pages for row in page.get("rows", [])]
        assert all(row["activity"] == event for row in obtained)
        assert len(obtained) == last["read_range"]["end"]
        assert len({row["date"] for row in obtained}) == len(obtained)
        assert "部分完成" in run["output"] and "未读取" in run["output"]
        assert f"{len(obtained)}/10" in run["output"]
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["content"] == run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert events.count('"name": "store_query"') == len(pages)
        assert "context_capacity" in events and "event: completed" in events
        assert "context_budget" not in events


async def test_finished_continuation_does_not_keep_first_page_partial_warning(tmp_path):
    def finish_page(model):
        first = model.results[-1]["targets"][0]
        assert first["has_more"] and first["read_range"] == {"start": 1, "end": 1}
        return ("store_query", {"continuations": [{"result_ref": first["result_ref"],
                "cursor": first["next_cursor"], "page_size": 200}]})

    model = QueryModel([
        ("store_data_catalog", {}),
        query([{"id": "days", "domain": "daily_ledger", "range": {"all_history": True},
                "fields": ["date"], "page_size": 1}]),
        finish_page,
        "全部两行已读取。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day in ("2026-07-01", "2026-07-02"):
            await save_day(client, day, 1)
        run = await ask(client, "按页读取全部历史日期")
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        last = model.results[-1]["targets"][0]
        assert last["read_range"] == {"start": 1, "end": 2}
        assert not last["has_more"] and last["next_cursor"] is None
        assert "全部两行已读取。" in run["output"]
        assert "部分完成" not in run["output"]
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["content"] == run["output"]


async def test_first_query_reserves_capacity_by_removing_old_answer_only(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "24000")
    old_answer = "旧回答。" * 3000

    class HistoryModel(QueryModel):
        def __init__(self, actions):
            super().__init__(actions)
            self.plans = iter(("general", "query"))

        async def stream_plan(self, messages, schemas):
            kind = next(self.plans)
            yield ToolCall("plan", "plan_response", json.dumps({"kind": kind, "queries": []}))

    model = HistoryModel([
        old_answer,
        ("store_data_catalog", {}),
        query([{"id": "today", "domain": "daily_ledger", "range": {"all_history": True},
                "fields": ["date", "daily_revenue"]}]),
        "已查询当前每日台账。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        first = await ask(client, "先讨论普通背景")
        assert first["status"] == "completed", json.dumps(first, ensure_ascii=False)
        history = (await client.get("/api/agent/1/conversation")).json()
        assert old_answer in history["messages"][-1]["content"]
        await save_day(client, "2026-07-01", 17)
        run = await ask(client, "查询全部历史每日台账金额")
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        assert model.results[-1]["targets"][0]["rows"] == [
            {"date": "2026-07-01", "daily_revenue": 17}]
        latest = model.messages[-1]
        assert not any(old_answer in (item.get("content") or "") for item in latest)
        assert any(item["role"] == "user" and item["content"] == "查询全部历史每日台账金额"
                   for item in latest)
        assert any(item["role"] == "user" and '"store_background"' in item["content"]
                   for item in latest)
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"name": "store_query"' in events and "event: completed" in events
        assert "context_budget" not in events


async def test_partial_notice_is_reserved_before_output_reaches_its_limit(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_OUTPUT_CHARS", "800")

    class NearLimitModel(QueryModel):
        emitted = 0

        async def stream_plan(self, messages, schemas):
            async for chunk in super().stream_plan(messages, schemas):
                self.emitted += len(chunk.arguments)
                yield chunk

        async def stream_tools(self, messages, schemas):
            async for chunk in super().stream_tools(messages, schemas):
                self.emitted += len(chunk.arguments) if isinstance(chunk, ToolCall) else len(chunk)
                yield chunk

    def almost_full(model):
        # Within the original model-output cap, but without room for the
        # required server explanation that one of two rows remains unread.
        return "结果。" * ((800 - model.emitted - 5) // 3)

    model = NearLimitModel([
        ("store_data_catalog", {}),
        query([{"id": "days", "domain": "daily_ledger", "range": {"all_history": True},
                "fields": ["date"], "page_size": 1}]),
        almost_full,
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day in ("2026-07-01", "2026-07-02"):
            await save_day(client, day, 1)
        run = await ask(client, "读取全部每日台账日期")
        assert model.emitted < 800
        target = model.results[-1]["targets"][0]
        assert target["has_more"] and target["result_ref"] and len(target["rows"]) == 1
        assert run["status"] == "failed" and run["error_code"] == "output_budget", run
        assert len(run["output"]) <= 800
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["role"] == "user"
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert "output_budget" in events and "event: completed" not in events


async def test_failed_large_row_is_disclosed_when_neighbor_is_complete(tmp_path):
    model = QueryModel([
        ("store_data_catalog", {}),
        query([
            {"id": "large", "domain": "daily_ledger", "range": {"all_history": True},
             "fields": ["date", "activity"]},
            {"id": "small", "domain": "daily_ledger", "range": {"all_history": True},
             "fields": ["date"]},
        ]),
        "已整理。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        saved = await client.put("/api/ledger/1/2026-07-01", json={
            "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
            "is_open": "营业", "daily_revenue": 1, "activity": "\u0001" * 2000})
        assert saved.status_code == 201, saved.text
        run = await ask(client, "读取全部历史完整事件和日期")
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        failed, success = model.results[-1]["targets"]
        assert failed["error"] == "row_too_large" and not failed.get("result_ref")
        assert success["rows"] == [{"date": "2026-07-01"}] and not success["has_more"]
        assert "部分完成" in run["output"] and "row_too_large" in run["output"]
        assert "1个查询目标未完成" in run["output"]
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["content"] == run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert "部分完成" in events and "row_too_large" in events and "event: completed" in events


async def test_new_batch_capacity_rejection_preserves_complete_prior_evidence(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "24000")
    first_query = query([{"id": "original", "domain": "daily_ledger",
                          "range": {"all_history": True}, "fields": ["date", "activity"]}])

    def refused_batch(model):
        original = model.results[-1]["targets"][0]
        assert original["status"] == "complete" and not original["has_more"], original
        model.original = original
        return query([{"id": chr(index + 1) * 63, "domain": "daily_ledger",
                       "range": {"all_history": True}, "fields": ["date"]}
                      for index in range(6)])(model)

    model = QueryModel([("store_data_catalog", {}), first_query, refused_batch,
                        "原查询完整事件已保留。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        saved = await client.put("/api/ledger/1/2026-07-01", json={
            "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
            "is_open": "营业", "daily_revenue": 1, "activity": "\u0001" * 800})
        assert saved.status_code == 201, saved.text
        run = await ask(client, "查询全部历史完整事件，再查询六组日期")
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert "context_capacity" in events, (run, events)
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        assert model.original["rows"] == [{"date": "2026-07-01", "activity": "\u0001" * 800}]
        assert "部分完成" in run["output"] and "context_capacity" in run["output"]
        assert "查询请求未完成" in run["output"]
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["content"] == run["output"]
        assert "context_budget" not in events and "event: completed" in events



async def test_low_capacity_invalid_continuations_have_stable_failure_ids(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "24000")
    references = [chr(index + 1) * 32 for index in range(6)]
    model = QueryModel([
        ("store_data_catalog", {}),
        query([{"id": "original", "domain": "daily_ledger",
                "range": {"all_history": True}, "fields": ["date", "activity"]}]),
        ("store_query", {"continuations": [
            {"result_ref": reference, "cursor": "\u0001" * 128}
            for reference in references]}),
        "原查询完成，无效续页未执行。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        saved = await client.put("/api/ledger/1/2026-07-01", json={
            "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
            "is_open": "营业", "daily_revenue": 1, "activity": "\u0001" * 800})
        assert saved.status_code == 201, saved.text
        run = await ask(client, "查询完整事件，检查六个无效续页")
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        assert "部分完成" in run["output"] and "invalid_result_reference" in run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert "internal_error" not in events and "context_budget" not in events
        assert "event: completed" in events
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["content"] == run["output"]
        # If room permits an answer-model call, the same receipts must expose ids.
        failures = [r for r in model.results if r.get("status") == "failed"]
        if failures:
            assert [t["id"] for t in failures[-1]["targets"]] == references
            assert all(t["error"] == "invalid_result_reference" and not t.get("rows")
                       for t in failures[-1]["targets"])

