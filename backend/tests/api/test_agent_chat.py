"""Public chat contract: real authentication and forward-migrated SQLite."""

import asyncio
import json
from contextlib import asynccontextmanager, closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from uuid import uuid4

import pytest
import httpx
import respx
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session, sqlite_url
from app.core.security import hash_password
from app.main import create_app
from app.core.config import Settings
from app.agents.providers.bailian import BailianChat
from app.agents.providers.bailian import ToolCall


def general_plan_sse():
    """Controlled planning response, separate from the streaming answer fixture."""
    call = {"index": 0, "id": "plan-1", "type": "function", "function": {
        "name": "plan_response", "arguments": '{"kind":"general","queries":[]}',
    }}
    return "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [call]},
                                               "finish_reason": "tool_calls"}]}) + "\n\ndata: [DONE]\n\n"


class StreamingModel:
    model_name = "controlled-model"

    def __init__(self):
        self.calls = []

    async def stream_plan(self, messages, schemas):
        # Existing answer/control tests use a valid general plan; grounding tests
        # independently exercise real planning, bypasses and business requirements.
        yield ToolCall("plan-1", "plan_response", '{"kind":"general","queries":[]}')

    async def stream(self, messages):
        self.calls.append(messages)
        yield "你好，"
        yield "有什么问题？"


class NoWeather:
    async def get_daily(self, store, target):
        return None


@asynccontextmanager
async def chat_app(tmp_path, model, *, historical_messages=0, memory_model=None, embedding=None, vectors=None):
    database = tmp_path / "chat.sqlite3"
    for revision in ("0022", "head"):
        subprocess.run(
            [sys.executable, "-m", "alembic", "upgrade", revision],
            cwd=Path(__file__).parents[2],
            env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(database)},
            check=True, capture_output=True,
        )
        if revision == "0022":
            with closing(sqlite3.connect(database)) as db, db:
                for index, role in enumerate(("admin", "admin", "user"), 1):
                    db.execute(
                        "INSERT INTO users (auth_identity, username, password_hash, role, is_active) "
                        "VALUES (?, ?, ?, ?, 1)",
                        (f"{index:064x}", f"user-{index}", hash_password("Password123"), role),
                    )
                for name in ("门店甲", "门店乙"):
                    db.execute(
                        "INSERT INTO stores (name, address, latitude, longitude, timezone, "
                        "is_active, income_items_enabled) VALUES (?, 'Roma', 45, 9, 'Europe/Rome', 1, 0)",
                        (name,),
                    )
                db.execute("INSERT INTO agent_conversations (user_id, store_id) VALUES (1, 1)")
                db.execute("INSERT INTO agent_messages (conversation_id, role, content) "
                           "VALUES (1, 'user', '历史问题'), (1, 'assistant', '历史回答')")
                for number in range(historical_messages):
                    db.execute("INSERT INTO agent_messages (conversation_id, role, content) "
                               "VALUES (1, 'user', ?)", (f"更多历史{number}",))
    engine = create_async_engine(sqlite_url(database))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(session_factory=factory, agent_model=model, memory_model=memory_model,
                     embedding=embedding, vectors=vectors,
                     weather_service=NoWeather())

    async def session_dependency():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = session_dependency
    try:
        async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver") as client:
            await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})
            yield client, app, factory
    finally:
        await app.state.agent_runner.close()
        await engine.dispose()


async def completed(client, run_id, store=1):
    # Allow the configured run budget under parallel Windows CI load. This polls
    # observable status; concurrency tests use provider/transport barriers instead.
    async with asyncio.timeout(65):
        while True:
            response = await client.get(f"/api/agent/{store}/runs/{run_id}")
            assert response.status_code == 200, response.text
            run = response.json()
            if run["status"] != "running":
                return run
            await asyncio.sleep(0.01)


async def test_stream_save_reload_and_scope_isolation(tmp_path):
    model = StreamingModel()
    async with chat_app(tmp_path, model) as (client, app, factory):
        before = await client.get("/api/agent/1/conversation")
        assert before.status_code == 200
        assert [item["content"] for item in before.json()["messages"]] == ["历史问题", "历史回答"]
        response = await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "你好"})
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        assert (await completed(client, run_id))["status"] == "completed"
        events = await client.get(f"/api/agent/1/runs/{run_id}/events")
        assert events.headers["content-type"].startswith("text/event-stream")
        assert "你好，" in events.text and "有什么问题？" in events.text
        assert "event: completed" in events.text
        for _ in range(2):
            read = (await client.get("/api/agent/1/conversation")).json()
            assert read["messages"][-1]["content"] == "记忆检索受限，本轮未参考长期记忆。\n\n你好，有什么问题？"
            await client.get(f"/api/agent/1/runs/{run_id}/events")
        assert len(model.calls) == 1
        restarted = create_app(session_factory=factory, agent_model=model)
        restarted.dependency_overrides[get_session] = app.dependency_overrides[get_session]
        async with AsyncClient(transport=ASGITransport(restarted), base_url="http://testserver",
                               cookies=client.cookies) as fresh:
            assert (await fresh.get("/api/agent/1/conversation")).json() == read
            await fresh.get(f"/api/agent/1/runs/{run_id}/events")
        assert len(model.calls) == 1
        assert (await client.get("/api/agent/2/conversation")).json()["messages"] == []
        assert (await client.get(f"/api/agent/2/runs/{run_id}")).status_code == 404
        await client.post("/api/auth/login", json={"username": "user-2", "password": "Password123"})
        assert (await client.get("/api/agent/1/conversation")).json()["messages"] == []
        assert (await client.get(f"/api/agent/1/runs/{run_id}/events")).status_code == 404
        await client.post("/api/auth/login", json={"username": "user-3", "password": "Password123"})
        for method, path, data in (
            ("GET", "/conversation", None), ("POST", "/messages", {"content": "拒绝"}),
            ("GET", f"/runs/{run_id}", None), ("GET", f"/runs/{run_id}/events", None),
        ):
            assert (await client.request(method, f"/api/agent/1{path}", json=data)).status_code == 403


def provider():
    return BailianChat(Settings(
        _env_file=None, agent_chat_base_url="https://bailian.test/v1",
        agent_chat_model="chosen-model", agent_chat_api_key="private-key",
    ))


@pytest.mark.parametrize("thinking", [None, False, True])
async def test_bailian_optional_thinking_mode_on_wire(thinking):
    settings = Settings(_env_file=None, agent_chat_base_url="https://bailian.test/v1",
                        agent_chat_model="chosen-model", agent_chat_api_key="private-key",
                        agent_chat_enable_thinking=thinking)
    body = ('data: {"choices":[{"delta":{"content":"回答"},"finish_reason":"stop"}]}\n\n'
            'data: [DONE]\n\n')
    with respx.mock() as mock:
        route = mock.post("https://bailian.test/v1/chat/completions").respond(200, text=body)
        assert [chunk async for chunk in BailianChat(settings).stream([])] == ["回答"]
        request = json.loads(route.calls[0].request.content)
        if thinking is None:
            assert "enable_thinking" not in request
        else:
            assert request["enable_thinking"] is thinking


async def test_chat_thinking_setting_does_not_override_memory_workload(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CHAT_ENABLE_THINKING", "false")
    monkeypatch.setenv("AUTOLAVA_AGENT_MEMORY_ENABLE_THINKING", "true")
    async with chat_app(tmp_path, StreamingModel()) as (_, app, _):
        assert app.state.agent_runner.settings.agent_chat_enable_thinking is False
        assert app.state.agent_runner.memory_model.settings.agent_chat_enable_thinking is True


@pytest.mark.parametrize("status,body,code,calls", [
    (429, "private-provider-body", "model_rate_limited", 2),
    (503, "private-provider-body", "model_unavailable", 2),
    (401, "private-key", "model_configuration", 1),
    (200, "data: broken-json\n\n", "model_format", 1),
    (200, 'data: {"choices":[{"delta":{"content":"部分回答"}}]}\n\n', "model_format", 1),
])
async def test_provider_errors_are_bounded_and_saved(tmp_path, status, body, code, calls, caplog):
    with respx.mock() as mock:
        transport = mock.post("https://bailian.test/v1/chat/completions").mock(
            return_value=httpx.Response(status, text=body),
        )
        async with chat_app(tmp_path, provider()) as (client, _, _):
            response = await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "私人问题"})
            run = await completed(client, response.json()["id"])
            assert run["status"] == "failed" and run["error_code"] == code
            assert run["calls"] == transport.call_count == calls
            read = (await client.get("/api/agent/1/conversation")).json()
            assert read["run"] == run
            assert read["messages"][-1]["role"] == "user"
            assert (await client.get("/api/admin/stores")).status_code == 200
            events = await client.get(f'/api/agent/1/runs/{run["id"]}/events')
            assert code in events.text
            assert "private-provider-body" not in events.text and "private-key" not in events.text
    assert "私人问题" not in caplog.text and "private-key" not in caplog.text


async def test_bailian_stream_and_usage_through_public_api(tmp_path):
    body = '\n\n'.join([
        'data: {"choices":[{"delta":{"role":"assistant","content":"你好"}}]}',
        'data: {"choices":[{"delta":{},"finish_reason":"stop"}]}',
        'data: {"choices":[],"usage":{"prompt_tokens":20,"completion_tokens":2,"total_tokens":22}}',
        'data: [DONE]',
    ]) + '\n\n'
    with respx.mock() as mock:
        transport = mock.post("https://bailian.test/v1/chat/completions").mock(
            side_effect=[httpx.Response(503), httpx.Response(200, text=general_plan_sse()),
                         httpx.Response(200, text=body)],
        )
        async with chat_app(tmp_path, provider()) as (client, _, _):
            response = await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "你好"})
            run = await completed(client, response.json()["id"])
            assert run["status"] == "completed" and run["output"].endswith("你好")
            assert run["usage"] == {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22}
            assert run["calls"] == transport.call_count == 3
            events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
            ids = [line.removeprefix("id: ") for line in events.splitlines() if line.startswith("id: ")]
            tail = (await client.get(f'/api/agent/1/runs/{run["id"]}/events',
                                    headers={"Last-Event-ID": ids[-2]})).text
            assert "event: completed" in tail and "event: delta" not in tail
            assert transport.call_count == 3


class WaitingModel(StreamingModel):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()
        self.ignore_cancel = False

    async def stream(self, messages):
        try:
            self.calls.append(messages)
            yield "已有片段"
            self.entered.set()
            try:
                await self.release.wait()
            except asyncio.CancelledError:
                if not self.ignore_cancel:
                    raise
                await self.release.wait()
            yield "不得泄漏的迟到回答"
        finally:
            self.closed.set()


async def test_request_identity_deduplicates_concurrent_submissions(tmp_path):
    model = WaitingModel()
    async with chat_app(tmp_path, model) as (client, _, _):
        payload = {"content": "只运行一次", "request_id": "same-request", "generation": 0}
        first, retry = await asyncio.gather(*[
            client.post("/api/agent/1/messages", json=payload) for _ in range(2)
        ])
        assert first.status_code == retry.status_code == 202
        assert first.json()["id"] == retry.json()["id"]
        await asyncio.wait_for(model.entered.wait(), 5)
        busy = await client.post("/api/agent/1/messages", json=payload | {"request_id": "different"})
        assert busy.status_code == 409
        conflict = await client.post("/api/agent/1/messages", json=payload | {"content": "不同问题"})
        assert conflict.status_code == 409
        model.release.set()
        run = await completed(client, first.json()["id"])
        again = await client.post("/api/agent/1/messages", json=payload)
        assert again.json() == run
        assert len(model.calls) == 1
        history = (await client.get("/api/agent/1/conversation")).json()["messages"]
        assert [m["content"] for m in history].count("只运行一次") == 1


@pytest.mark.parametrize("action", ["stop", "reset"])
async def test_stop_and_reset_fence_late_model_and_retries(tmp_path, action):
    model = WaitingModel()
    model.ignore_cancel = True
    async with chat_app(tmp_path, model) as (client, _, _):
        payload = {"content": "等待", "request_id": "old-request", "generation": 0}
        run = (await client.post("/api/agent/1/messages", json=payload)).json()
        await asyncio.wait_for(model.entered.wait(), 5)
        path = f'/runs/{run["id"]}/stop' if action == "stop" else "/conversation/reset"
        result = await client.post(f"/api/agent/1{path}", json={"generation": 0})
        assert result.status_code == 200, result.text
        model.release.set()
        await asyncio.wait_for(model.closed.wait(), 5)
        saved = (await client.get(f'/api/agent/1/runs/{run["id"]}')).json()
        assert saved["status"] == "failed"
        assert saved["error_code"] == ("cancelled" if action == "stop" else "reset")
        events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
        assert "不得泄漏" not in events and "event: completed" not in events
        history = (await client.get("/api/agent/1/conversation")).json()
        retry = await client.post("/api/agent/1/messages", json=payload)
        if action == "reset":
            assert history == {"generation": 1, "messages": [], "run": None, "next_before": None}
            assert retry.status_code == 409
            # A retried reset cannot erase a newer generation.
            assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 409
        else:
            assert history["messages"][-1]["content"] == "等待"
            assert retry.json()["id"] == run["id"]
        assert len(model.calls) == 1
        new = await client.post("/api/agent/1/messages", json=payload | {
            "request_id": "new-request", "generation": history["generation"],
        })
        assert new.status_code == 202
        assert (await completed(client, new.json()["id"]))["status"] == "completed"


async def test_startup_marks_orphan_interrupted_without_calling_model(tmp_path):
    model = WaitingModel()
    async with chat_app(tmp_path, model) as (client, app, factory):
        payload = {"content": "服务中断", "request_id": "orphan", "generation": 0}
        run = (await client.post("/api/agent/1/messages", json=payload)).json()
        await asyncio.wait_for(model.entered.wait(), 5)
        fresh_model = StreamingModel()
        restarted = create_app(session_factory=factory, agent_model=fresh_model, weather_service=NoWeather())
        restarted.dependency_overrides[get_session] = app.dependency_overrides[get_session]
        async with restarted.router.lifespan_context(restarted):
            async with AsyncClient(transport=ASGITransport(restarted), base_url="http://testserver",
                                   cookies=client.cookies) as fresh:
                restored = (await fresh.get("/api/agent/1/conversation")).json()["run"]
                assert restored["status"] == "failed" and restored["error_code"] == "interrupted"
                assert restored["output"].endswith("已有片段")
                replay = await fresh.get(f'/api/agent/1/runs/{run["id"]}/events')
                assert "interrupted" in replay.text and "event: completed" not in replay.text
                assert (await fresh.post("/api/agent/1/messages", json=payload)).json() == restored
                assert fresh_model.calls == []
                model.release.set()
                await asyncio.wait_for(model.closed.wait(), 5)
                retry = await fresh.post("/api/agent/1/messages", json=payload | {"request_id": "explicit-retry"})
                assert (await completed(fresh, retry.json()["id"]))["status"] == "completed"
                assert len(fresh_model.calls) == 1


@pytest.mark.parametrize("reset", [False, True])
async def test_disconnect_active_sse_and_resume_from_consumed_cursor(tmp_path, reset):
    model = WaitingModel()
    async with chat_app(tmp_path, model) as (client, app, _):
        run = (await client.post("/api/agent/1/messages", json={
            "content": "断线", "request_id": "disconnect", "generation": 0,
        })).json()
        await asyncio.wait_for(model.entered.wait(), 5)
        path = f'/api/agent/1/runs/{run["id"]}/events'
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
                if "已有片段".encode() in bodies[-1]:
                    disconnected.set()

        # ASGI's HTTP transport lets the client disconnect at an exact streamed event,
        # without buffering the entire response or sleeping to race the provider.
        await asyncio.wait_for(app({
            "type": "http", "asgi": {"version": "3.0", "spec_version": "2.0"},
            "http_version": "1.1", "method": "GET", "scheme": "http", "path": path,
            "raw_path": path.encode(), "query_string": b"", "root_path": "",
            "headers": [(name.lower(), value) for name, value in request.headers.raw],
            "server": ("testserver", 80), "client": ("127.0.0.1", 1234),
        }, receive, send), 5)
        text = b"".join(bodies).decode()
        cursor = [line[4:] for line in text.splitlines() if line.startswith("id: ")][-1]
        assert "已有片段" in text
        if reset:
            assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
        model.release.set()
        await completed(client, run["id"])
        resumed = await client.get(path, headers={"Last-Event-ID": cursor})
        assert "已有片段" not in resumed.text
        assert ("reset" if reset else "event: completed") in resumed.text
        ids = [int(line[4:]) for line in resumed.text.splitlines() if line.startswith("id: ")]
        assert ids and min(ids) > int(cursor)
        assert len(model.calls) == 1


async def test_waiting_model_does_not_lock_business_and_revoked_session_cannot_finish(tmp_path):
    model = WaitingModel()
    async with chat_app(tmp_path, model) as (client, _, _):
        submitted = await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "等待"})
        run_id = submitted.json()["id"]
        await asyncio.wait_for(model.entered.wait(), 5)
        assert (await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "重复"})).status_code == 409
        # An actual unrelated business write completes while the provider is suspended.
        async with asyncio.timeout(2):
            response = await client.patch("/api/admin/stores/2", json={"name": "等待期间修改"})
            assert response.status_code == 200
            assert (await client.post("/api/auth/logout")).status_code == 204
        model.release.set()
        await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})
        run = await completed(client, run_id)
        assert run["error_code"] == "access_revoked"
        assert run["output"].endswith("已有片段")
        events = (await client.get(f"/api/agent/1/runs/{run_id}/events")).text
        assert "不得泄漏" not in events
        assert len(model.calls) == 1


async def test_missing_configuration_timeout_and_output_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CHAT_MODEL", "")
    async with chat_app(tmp_path, None) as (client, _, _):
        run = (await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "你好"})).json()
        assert (await completed(client, run["id"]))["error_code"] == "model_not_configured"
    # Each case uses its own real migrated database.
    timeout_path = tmp_path / "timeout"
    timeout_path.mkdir()
    monkeypatch.setenv("AUTOLAVA_AGENT_TIMEOUT_SECONDS", "0.2")
    from app.core.config import get_settings
    get_settings.cache_clear()
    async with chat_app(timeout_path, WaitingModel()) as (client, _, _):
        run = (await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "等待"})).json()
        assert (await completed(client, run["id"]))["error_code"] == "model_timeout"
    output_path = tmp_path / "output"
    output_path.mkdir()
    monkeypatch.setenv("AUTOLAVA_AGENT_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("AUTOLAVA_AGENT_OUTPUT_CHARS", "2")
    get_settings.cache_clear()
    async with chat_app(output_path, StreamingModel()) as (client, _, _):
        run = (await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "等待"})).json()
        assert (await completed(client, run["id"]))["error_code"] == "output_budget"


async def test_history_pagination_input_scope_and_context_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "8000")
    model = StreamingModel()
    async with chat_app(tmp_path, model, historical_messages=101) as (client, _, _):
        recent = (await client.get("/api/agent/1/conversation")).json()
        assert len(recent["messages"]) == 100 and recent["next_before"]
        older = (await client.get("/api/agent/1/conversation", params={"before": recent["next_before"]})).json()
        assert older["next_before"] is None
        assert older["messages"][0]["content"] == "历史问题"
        assert len(older["messages"]) == 3
        for content in ("上一条" * 1500, "当前问题" * 1500):
            run = (await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": content})).json()
            assert (await completed(client, run["id"]))["status"] == "completed"
        assert sum(len(item["content"]) for item in model.calls[-1]) <= 8000
        assert model.calls[-1][-1]["content"] == "当前问题" * 1500
        for body in ({"content": " "}, {"content": "x" * 6001}, {"content": "hi", "user_id": 2}):
            assert (await client.post("/api/agent/1/messages", json={
                "request_id": uuid4().hex, "generation": 0, **body,
            })).status_code == 422
        assert (await client.get("/api/agent/999/conversation")).status_code == 404


async def test_final_administrator_and_store_revocation(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "user-3")
    model = WaitingModel()
    async with chat_app(tmp_path, model) as (client, _, _):
        await client.post("/api/auth/login", json={"username": "user-3", "password": "Password123"})
        submitted = await client.post("/api/agent/1/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "最终管理员"})
        assert submitted.status_code == 202
        run_id = submitted.json()["id"]
        await asyncio.wait_for(model.entered.wait(), 5)
        replay = asyncio.create_task(client.get(f"/api/agent/1/runs/{run_id}/events"))
        assert (await client.patch("/api/admin/stores/1", json={"is_active": False})).status_code == 200
        assert (await client.get(f"/api/agent/1/runs/{run_id}/events")).status_code == 404
        model.release.set()
        # Provider cleanup is a deterministic barrier after the rejected late chunk.
        await asyncio.wait_for(model.closed.wait(), 5)
        stream = await asyncio.wait_for(replay, 5)
        assert "不得泄漏" not in stream.text
        assert stream.status_code == 404 or "access_revoked" in stream.text
        allowed = (await client.post("/api/agent/2/messages", json={"request_id": uuid4().hex, "generation": 0, "content": "另一个启用门店"})).json()
        assert (await completed(client, allowed["id"], store=2))["status"] == "completed"
