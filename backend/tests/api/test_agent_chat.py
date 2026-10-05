"""Public chat contract: real authentication and forward-migrated SQLite."""

import asyncio
from contextlib import asynccontextmanager, closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys

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


class StreamingModel:
    model_name = "controlled-model"

    def __init__(self):
        self.calls = []

    async def stream(self, messages):
        self.calls.append(messages)
        yield "你好，"
        yield "有什么问题？"


class NoWeather:
    async def get_daily(self, store, target):
        return None


@asynccontextmanager
async def chat_app(tmp_path, model, *, historical_messages=0):
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
    app = create_app(session_factory=factory, agent_model=model, weather_service=NoWeather())

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
    async with asyncio.timeout(10):
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
        response = await client.post("/api/agent/1/messages", json={"content": "你好"})
        assert response.status_code == 202, response.text
        run_id = response.json()["id"]
        assert (await completed(client, run_id))["status"] == "completed"
        events = await client.get(f"/api/agent/1/runs/{run_id}/events")
        assert events.headers["content-type"].startswith("text/event-stream")
        assert "你好，" in events.text and "有什么问题？" in events.text
        assert "event: completed" in events.text
        for _ in range(2):
            read = (await client.get("/api/agent/1/conversation")).json()
            assert read["messages"][-1]["content"] == "你好，有什么问题？"
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
            response = await client.post("/api/agent/1/messages", json={"content": "私人问题"})
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
            side_effect=[httpx.Response(503), httpx.Response(200, text=body)],
        )
        async with chat_app(tmp_path, provider()) as (client, _, _):
            response = await client.post("/api/agent/1/messages", json={"content": "你好"})
            run = await completed(client, response.json()["id"])
            assert run["status"] == "completed" and run["output"] == "你好"
            assert run["usage"] == {"prompt_tokens": 20, "completion_tokens": 2, "total_tokens": 22}
            assert run["calls"] == transport.call_count == 2
            events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
            ids = [line.removeprefix("id: ") for line in events.splitlines() if line.startswith("id: ")]
            tail = (await client.get(f'/api/agent/1/runs/{run["id"]}/events',
                                    headers={"Last-Event-ID": ids[-2]})).text
            assert "event: completed" in tail and "event: delta" not in tail
            assert transport.call_count == 2


class WaitingModel(StreamingModel):
    def __init__(self):
        super().__init__()
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.closed = asyncio.Event()

    async def stream(self, messages):
        try:
            self.calls.append(messages)
            yield "已有片段"
            self.entered.set()
            await self.release.wait()
            yield "不得泄漏的迟到回答"
        finally:
            self.closed.set()


async def test_waiting_model_does_not_lock_business_and_revoked_session_cannot_finish(tmp_path):
    model = WaitingModel()
    async with chat_app(tmp_path, model) as (client, _, _):
        submitted = await client.post("/api/agent/1/messages", json={"content": "等待"})
        run_id = submitted.json()["id"]
        await asyncio.wait_for(model.entered.wait(), 5)
        assert (await client.post("/api/agent/1/messages", json={"content": "重复"})).status_code == 409
        # An actual unrelated business write completes while the provider is suspended.
        async with asyncio.timeout(2):
            response = await client.patch("/api/admin/stores/2", json={"name": "等待期间修改"})
            assert response.status_code == 200
            assert (await client.post("/api/auth/logout")).status_code == 204
        model.release.set()
        await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})
        run = await completed(client, run_id)
        assert run["error_code"] == "access_revoked"
        assert run["output"] == "已有片段"
        events = (await client.get(f"/api/agent/1/runs/{run_id}/events")).text
        assert "不得泄漏" not in events
        assert len(model.calls) == 1


async def test_missing_configuration_timeout_and_output_budget(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CHAT_MODEL", "")
    async with chat_app(tmp_path, None) as (client, _, _):
        run = (await client.post("/api/agent/1/messages", json={"content": "你好"})).json()
        assert (await completed(client, run["id"]))["error_code"] == "model_not_configured"
    # Each case uses its own real migrated database.
    timeout_path = tmp_path / "timeout"
    timeout_path.mkdir()
    monkeypatch.setenv("AUTOLAVA_AGENT_TIMEOUT_SECONDS", "0.2")
    from app.core.config import get_settings
    get_settings.cache_clear()
    async with chat_app(timeout_path, WaitingModel()) as (client, _, _):
        run = (await client.post("/api/agent/1/messages", json={"content": "等待"})).json()
        assert (await completed(client, run["id"]))["error_code"] == "model_timeout"
    output_path = tmp_path / "output"
    output_path.mkdir()
    monkeypatch.setenv("AUTOLAVA_AGENT_TIMEOUT_SECONDS", "10")
    monkeypatch.setenv("AUTOLAVA_AGENT_OUTPUT_CHARS", "2")
    get_settings.cache_clear()
    async with chat_app(output_path, StreamingModel()) as (client, _, _):
        run = (await client.post("/api/agent/1/messages", json={"content": "等待"})).json()
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
            run = (await client.post("/api/agent/1/messages", json={"content": content})).json()
            assert (await completed(client, run["id"]))["status"] == "completed"
        assert sum(len(item["content"]) for item in model.calls[-1]) <= 8000
        assert model.calls[-1][-1]["content"] == "当前问题" * 1500
        for body in ({"content": " "}, {"content": "x" * 6001}, {"content": "hi", "user_id": 2}):
            assert (await client.post("/api/agent/1/messages", json=body)).status_code == 422
        assert (await client.get("/api/agent/999/conversation")).status_code == 404


async def test_final_administrator_and_store_revocation(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "user-3")
    model = WaitingModel()
    async with chat_app(tmp_path, model) as (client, _, _):
        await client.post("/api/auth/login", json={"username": "user-3", "password": "Password123"})
        submitted = await client.post("/api/agent/1/messages", json={"content": "最终管理员"})
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
        allowed = (await client.post("/api/agent/2/messages", json={"content": "另一个启用门店"})).json()
        assert (await completed(client, allowed["id"], store=2))["status"] == "completed"
