"""Pagination reference and lifecycle isolation at authenticated HTTP/SSE boundaries."""

import asyncio
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient

from app.agents.providers.bailian import ToolCall
from tests.api.test_agent_chat import chat_app, completed
from tests.api.test_agent_pagination import latest_batch, save_event
from tests.api.test_agent_store_query import QueryModel, catalog, query
from tests.api.test_agent_tools import ask


LATE_EVENT = "只应在合法续页出现的完整事件"


def detail(identifier):
    return {"id": identifier, "domain": "daily_ledger", "range": {"all_history": True},
            "fields": ["date", "activity"], "page_size": 1}


async def seed_events(client):
    for day in range(1, 4):
        await save_event(client, f"2026-07-{day:02}", day,
                         "已读首行" if day == 1 else LATE_EVENT)


def continuation(target):
    return {"result_ref": target["result_ref"], "cursor": target["next_cursor"], "page_size": 1}


async def test_forged_and_exchanged_cursors_fail_without_consuming_valid_pages(tmp_path, monkeypatch):
    # This scenario isolates reference validation; accumulated capacity has separate acceptance.
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    def attacks(model):
        model.original = latest_batch(model)["targets"]
        offset, signature, unicode, left, right = model.original
        modified_offset = continuation(offset)
        version, position, digest = modified_offset["cursor"].split(".")
        modified_offset["cursor"] = f"{version}.{int(position, 16) + 1:x}.{digest}"
        modified_signature = continuation(signature)
        token = modified_signature["cursor"]
        modified_signature["cursor"] = token[:-1] + ("0" if token[-1] != "0" else "1")
        modified_unicode = continuation(unicode)
        modified_unicode["cursor"] = modified_unicode["cursor"][:-1] + "中"
        return "store_query", {"continuations": [
            {**continuation(offset), "result_ref": "f" * 32}, modified_offset,
            modified_signature, modified_unicode,
            {**continuation(left), "cursor": right["next_cursor"]},
            {**continuation(right), "cursor": left["next_cursor"]},
        ]}

    def retry_valid(model):
        rejected = latest_batch(model)
        assert rejected["status"] == "failed", rejected
        assert len(rejected["targets"]) == 6
        assert all(target["error"] == "invalid_result_reference"
                   and not target.get("rows") for target in rejected["targets"])
        assert LATE_EVENT not in json.dumps(rejected, ensure_ascii=False)
        return "store_query", {"continuations": [continuation(model.original[0])]}

    model = QueryModel([("store_data_catalog", {}),
                        query([detail(name) for name in ("offset", "signature", "unicode", "left", "right")]),
                        attacks, retry_valid, "基于已读取页面说明，剩余内容尚未读取。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await seed_events(client)
        run = await ask(client, "查询完整事件并检查分页引用")
        assert run["status"] == "completed", run
        recovered = latest_batch(model)["targets"][0]
        assert recovered["page_range"] == {"start": 2, "end": 2}
        assert recovered["read_range"] == {"start": 1, "end": 2}
        assert recovered["rows"] == [{"date": "2026-07-02", "activity": LATE_EVENT}]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert events.count('"name": "store_query"') == 3
        assert events.count('"name": "store_data_catalog"') == 1
        assert '"status": "denied"' in events and "query_targets_failed" in events


async def test_continuation_reselection_and_mixed_modes_reject_advertised_schema(tmp_path):
    def illegal(kind):
        def call(model):
            initial = next(result["targets"][0] for result in model.results if "targets" in result)
            arguments = {"continuations": [continuation(initial)]}
            if kind == "fields":
                arguments["continuations"][0]["fields"] = ["daily_revenue"]
            elif kind == "range":
                arguments["continuations"][0]["range"] = {"start": "2026-07-02", "end": "2026-07-03"}
            elif kind == "catalog":
                arguments["catalog_version"] = catalog(model)["catalog_version"]
            else:
                arguments.update(catalog_version=catalog(model)["catalog_version"], targets=[detail("new")])
            return "store_query", arguments
        return call

    def final(model):
        rejected = [result for result in model.results if result.get("error") == "invalid_tool_arguments"]
        assert len(rejected) == 4, model.results
        assert all(not result.get("targets") for result in rejected)
        assert all(LATE_EVENT not in json.dumps(result, ensure_ascii=False) for result in rejected)
        return "四类续页参数均已拒绝，只完成原查询的第一页。"

    model = QueryModel([("store_data_catalog", {}), query([detail("original")]),
                        *[illegal(kind) for kind in ("fields", "range", "catalog", "new_targets")], final])
    async with chat_app(tmp_path, model) as (client, _, _):
        await seed_events(client)
        run = await ask(client, "按原查询继续完整事件")
        assert run["status"] == "completed", run
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert events.count('"name": "store_query"') == 5
        assert events.count('"error_code": "invalid_tool_arguments"') == 4
        assert "event: completed" in events


async def test_completed_reference_cannot_cross_run_administrator_store_or_generation(tmp_path):
    def remember(model):
        model.saved = latest_batch(model)["targets"][0]
        assert model.saved["has_more"]
        return "本轮仅取得首行，其余尚未读取。"

    def reuse(model):
        return "store_query", {"continuations": [continuation(model.saved)]}

    def rejected(model):
        result = latest_batch(model)
        assert result["status"] == "failed" and result["targets"][0]["error"] == "invalid_result_reference"
        assert not result["targets"][0].get("rows")
        assert LATE_EVENT not in json.dumps(result, ensure_ascii=False)
        return "旧引用未获访问。"

    model = QueryModel([("store_data_catalog", {}), query([detail("old")]), remember,
                        *[action for _ in range(4) for action in (reuse, rejected)]])
    async with chat_app(tmp_path, model) as (client, _, _):
        await seed_events(client)
        original = await ask(client, "取得事件第一页")
        assert original["status"] == "completed", original
        original_sse = (await client.get(f"/api/agent/1/runs/{original['id']}/events")).text
        assert original_sse.count('"name": "store_query"') == 1
        for scope in ("new_run", "administrator", "store", "generation"):
            if scope == "administrator":
                assert (await client.post("/api/auth/login", json={
                    "username": "user-2", "password": "Password123"})).status_code == 200
            if scope == "store":
                assert (await client.post("/api/auth/login", json={
                    "username": "user-1", "password": "Password123"})).status_code == 200
            store_id = 2 if scope == "store" else 1
            history = (await client.get(f"/api/agent/{store_id}/conversation")).json()
            if scope == "generation":
                reset = await client.post("/api/agent/1/conversation/reset", json={"generation": history["generation"]})
                assert reset.status_code == 200, reset.text
                history = reset.json()
                assert history["generation"] == 1
            submitted = await client.post(f"/api/agent/{store_id}/messages", json={
                "request_id": uuid4().hex, "generation": history["generation"], "content": f"复用旧引用 {scope}"})
            assert submitted.status_code == 202, submitted.text
            run = await completed(client, submitted.json()["id"], store=store_id)
            assert run["status"] == "failed" and run["error_code"] == "grounding_unavailable", run
            events = (await client.get(f"/api/agent/{store_id}/runs/{run['id']}/events")).text
            assert events.count('"name": "store_query"') == 1
            assert "query_targets_failed" in events and "event: completed" not in events
            current = (await client.get(f"/api/agent/{store_id}/conversation")).json()
            assert LATE_EVENT not in json.dumps(current, ensure_ascii=False)


class PausedPaginationModel(QueryModel):
    def __init__(self):
        super().__init__([("store_data_catalog", {}), query([detail("paused")])])
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.paused = False
        self.late_results = []

    async def stream_tools(self, messages, tools):
        results = [json.loads(item["content"]) for item in messages if item["role"] == "tool"]
        batches = [result for result in results if "targets" in result]
        if batches and not self.paused:
            self.paused = True
            self.results = results
            self.messages.append(messages)
            self.first_page = batches[-1]["targets"][0]
            self.entered.set()
            try:
                try:
                    await self.release.wait()
                except asyncio.CancelledError:
                    # Simulate a late provider that sends a real tool call despite stop/reset.
                    await self.release.wait()
                yield ToolCall(uuid4().hex, "store_query", json.dumps({
                    "continuations": [continuation(self.first_page)]}))
            finally:
                self.closed.set()
            return
        if self.paused:
            self.late_results = batches[1:]
            yield "不应保存的迟到续页回答：" + LATE_EVENT
            return
        async for chunk in super().stream_tools(messages, tools):
            yield chunk


async def first_query_sse(client, app, run_id):
    """Read and disconnect a real SSE response after the first query receipt."""
    path = f"/api/agent/1/runs/{run_id}/events"
    request = client.build_request("GET", path)
    disconnected = asyncio.Event()
    bodies = []
    received = False

    async def receive():
        nonlocal received
        if not received:
            received = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await disconnected.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        if message["type"] == "http.response.body":
            bodies.append(message.get("body", b""))
            if b'"name": "store_query"' in bodies[-1]:
                disconnected.set()

    await asyncio.wait_for(app({
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
        "http_version": "1.1", "method": "GET", "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": b"", "root_path": "",
        "headers": [(name.lower(), value) for name, value in request.headers.raw],
        "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
    }, receive, send), 5)
    return b"".join(bodies).decode()


@pytest.mark.parametrize("control", ["stop", "reset", "logout", "deactivate"])
async def test_control_after_snapshot_rejects_late_continuation_and_history(tmp_path, monkeypatch, control):
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "user-3")
    model = PausedPaginationModel()
    async with chat_app(tmp_path, model) as (client, app, _):
        await seed_events(client)
        submitted = await client.post("/api/agent/1/messages", json={
            "request_id": uuid4().hex, "generation": 0, "content": "先读取事件然后继续分页"})
        assert submitted.status_code == 202, submitted.text
        run_id = submitted.json()["id"]
        await asyncio.wait_for(model.entered.wait(), 5)
        assert model.first_page["rows"] == [{"date": "2026-07-01", "activity": "已读首行"}]
        assert model.first_page["has_more"]
        initial_sse = await first_query_sse(client, app, run_id)
        assert initial_sse.count('"name": "store_query"') == 1
        async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver") as owner:
            if control == "stop":
                result = await client.post(f"/api/agent/1/runs/{run_id}/stop")
                assert result.status_code == 200, result.text
            elif control == "reset":
                result = await client.post("/api/agent/1/conversation/reset", json={"generation": 0})
                assert result.status_code == 200, result.text
            elif control == "logout":
                assert (await client.post("/api/auth/logout")).status_code == 204
            else:
                assert (await owner.post("/api/auth/login", json={
                    "username": "user-3", "password": "Password123"})).status_code == 200
                disabled = await owner.patch("/api/admin/users/1", json={"is_active": False})
                assert disabled.status_code == 200, disabled.text
                assert (await client.get(f"/api/agent/1/runs/{run_id}")).status_code == 401
            model.release.set()
            await asyncio.wait_for(model.closed.wait(), 5)
            if control == "deactivate":
                enabled = await owner.patch("/api/admin/users/1", json={"is_active": True})
                assert enabled.status_code == 200, enabled.text
            if control in ("logout", "deactivate"):
                assert (await client.post("/api/auth/login", json={
                    "username": "user-1", "password": "Password123"})).status_code == 200
            run = await completed(client, run_id)
            assert run["status"] == "failed", run
            assert run["error_code"] == {"stop": "cancelled", "reset": "reset"}.get(control, "access_revoked"), run
            events = (await client.get(f"/api/agent/1/runs/{run_id}/events")).text
            assert "event: completed" not in events
            assert '"name": "store_query"' not in events
            assert LATE_EVENT not in events and "迟到续页回答" not in events
            history = (await client.get("/api/agent/1/conversation")).json()
            assert LATE_EVENT not in json.dumps(history, ensure_ascii=False)
            assert not model.late_results
            if control == "reset":
                assert history["generation"] == 1 and history["messages"] == []


async def test_valid_retry_clears_invalid_cursor_failure_after_all_rows_read(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")

    def bad_cursor(model):
        model.original = latest_batch(model)["targets"][0]
        invalid = continuation(model.original)
        token = invalid["cursor"]
        invalid["cursor"] = token[:-1] + ("0" if token[-1] != "0" else "1")
        return "store_query", {"continuations": [invalid]}

    def correct_cursor(model):
        rejected = latest_batch(model)["targets"][0]
        assert rejected["error"] == "invalid_result_reference" and not rejected.get("rows")
        return "store_query", {"continuations": [{**continuation(model.original), "page_size": 200}]}

    model = QueryModel([("store_data_catalog", {}), query([detail("events")]),
                        bad_cursor, correct_cursor, "全部三行事件已读取。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await seed_events(client)
        run = await ask(client, "按页查询全部事件，无效游标后重试正确续页")
        assert run["status"] == "completed", json.dumps(run, ensure_ascii=False)
        last = latest_batch(model)["targets"][0]
        assert last["read_range"] == {"start": 1, "end": 3}
        assert not last["has_more"] and last["next_cursor"] is None
        assert "全部三行事件已读取。" in run["output"]
        assert "部分完成" not in run["output"] and "invalid_result_reference" not in run["output"]
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["content"] == run["output"]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert "query_targets_failed" in events and "event: completed" in events
        assert events.count('"name": "store_query"') == 3
