"""T9 cross-feature acceptance: HTTP/SSE, migrated SQLite and persistent Qdrant.

Only model/embedding responses are controlled; barriers represent external waits.
"""
import asyncio
from contextlib import asynccontextmanager, closing
import sqlite3

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.core.database import get_session, sqlite_url
from app.main import create_app
from app.agents.providers.bailian import ModelFailure
from app.agents.providers.qdrant import MemoryVectors
from tests.api.test_agent_chat import StreamingModel, chat_app, completed
from tests.api.test_agent_memory import save
from tests.api.test_agent_vectors import Embedding, background, configured, wait_status  # noqa: F401
from tests.api.test_memory_jobs import BackgroundCurator, settled, turn

pytestmark = pytest.mark.usefixtures("configured")


@asynccontextmanager
async def restored_app(database, cookies, chat, curator):
    engine = create_async_engine(sqlite_url(database))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    app = create_app(session_factory=factory, agent_model=chat, memory_model=curator,
                     embedding=Embedding())

    async def sessions():
        async with factory() as session:
            yield session

    app.dependency_overrides[get_session] = sessions
    try:
        async with app.router.lifespan_context(app):
            async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver",
                                   cookies=cookies) as client:
                yield client, app
    finally:
        await app.state.agent_runner.close()
        await engine.dispose()


async def test_automatic_memory_reset_restart_correction_backup_restore_and_deletion(
    tmp_path, monkeypatch,
):
    # The actual final-admin download endpoint must back up the test database.
    monkeypatch.setenv("AUTOLAVA_DATABASE_PATH", str(tmp_path / "chat.sqlite3"))
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "user-1")
    get_settings.cache_clear()
    curator, chat = BackgroundCurator(), StreamingModel()
    async with chat_app(tmp_path, chat, memory_model=curator, embedding=Embedding()) as (client, app, _):
        async with app.router.lifespan_context(app):
            run = await turn(client, "以后分析先给结论，再列数据")
            job = await settled(client, run["id"])
            assert job["result"]["status"] == "saved"
            await wait_status(client, "available")
            item = (await client.get("/api/agent/1/memories")).json()["items"][0]
            assert item["sources"][0]["evidence"] == "以后分析先给结论，再列数据"
            curator.action = "reject"
            assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
        cookies = client.cookies

    # A new app/engine and actual close/reopen of the Qdrant files.
    chat = StreamingModel()
    async with restored_app(tmp_path / "chat.sqlite3", cookies, chat, curator) as (client, app):
        await wait_status(client, "available")
        await save(client, "换一种说法，我希望怎样看分析？", generation=1)
        assert background(chat)["memories"] == [{k: item[k] for k in ("id", "version", "content")}]
        assert (await client.get("/api/agent/2/memories")).json()["items"] == []
        other = await client.post("/api/agent/2/messages", json={
            "generation": 0, "request_id": "other-store", "content": "我的偏好？",
        })
        assert (await completed(client, other.json()["id"], store=2))["status"] == "completed"
        assert background(chat)["memories"] == []
        await client.post("/api/auth/login", json={"username": "user-2", "password": "Password123"})
        await save(client, "我的偏好？")
        assert background(chat)["memories"] == []
        await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})
        path = f'/api/agent/1/memories/{item["id"]}'
        updated = await client.patch(path, json={"expected_version": 1, "content": "以后先列数据，再给结论"})
        assert updated.status_code == 200, updated.text
        await wait_status(client, "available")
        probe = await save(client, "现在的分析偏好？", generation=1)
        assert background(chat)["memories"] == [{"id": item["id"], "version": 2, "content": "以后先列数据，再给结论"}]
        # Main completion only enqueues curation. Do not change the fake's response
        # until this queued query has consumed its intended rejection response.
        assert (await settled(client, probe["id"]))["result"]["status"] == "not_saved"

        # Keep a second deleted record in the same backup, alongside a failed job.
        curator.action = "save"
        await save(client, "记住：以后回答简短", generation=1)
        listing = (await client.get("/api/agent/1/memories")).json()
        deleted = next(m for m in listing["items"] if m["id"] != item["id"])
        assert (await client.request("DELETE", f'/api/agent/1/memories/{deleted["id"]}',
                                    json={"expected_version": 1})).status_code == 204
        curator.action = "reject"
        await wait_status(client, "available")
        curator.failure = ModelFailure("model_unavailable", retryable=True)
        failed = await save(client, "以后请用另一种分析格式", generation=1)
        failed_job = await settled(client, failed["id"])
        assert failed_job["status"] == "failed" and failed_job["calls"] == 2
        curator.failure = None
        before = (await client.get("/api/agent/1/memories")).json()
        jobs = (await client.get("/api/agent/1/memory-jobs")).json()
        snapshot = await client.get("/api/admin/database-backup")
        assert snapshot.status_code == 200, snapshot.text[:200]
        backup = tmp_path / "restored.sqlite3"
        backup.write_bytes(snapshot.content)
        # Schema/state inspection supplements the public restored behavior below.
        with closing(sqlite3.connect(backup)) as db:
            assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
            assert db.execute("SELECT version_num FROM alembic_version").fetchone() == ("0030",)
            assert db.execute("SELECT deleted FROM agent_memories WHERE id=?", (deleted["id"],)).fetchone() == (1,)
        cookies = client.cookies

    # Deliberately restore ONLY SQLite into new vector storage: no vector backup.
    monkeypatch.setenv("AUTOLAVA_AGENT_VECTOR_PATH", str(tmp_path / "restored-vectors"))
    get_settings.cache_clear()
    chat = StreamingModel()
    async with restored_app(backup, cookies, chat, curator) as (client, app):
        await wait_status(client, "available")
        actual = (await client.get("/api/agent/1/memories")).json()
        assert actual["items"] == before["items"]
        assert actual["revision"] == before["revision"]
        assert (await client.get("/api/agent/1/memory-jobs")).json() == jobs
        await save(client, "恢复后我的偏好？", generation=1)
        assert [m["content"] for m in background(chat)["memories"]] == ["以后先列数据，再给结论"]
        assert (await client.request("DELETE", path, json={"expected_version": 2})).status_code == 204
        for operation in ("retry", "rebuild"):
            assert (await client.post(f"/api/agent/1/memory-index/{operation}")).status_code == 200
            await wait_status(client, "available")
        await save(client, "重建后我的偏好？", generation=1)
        assert background(chat)["memories"] == []
        assert (await client.get("/api/agent/1/memories")).json()["items"] == []


@pytest.mark.parametrize("action", ["correct", "delete", "clear", "reset", "description", "description_clear"])
async def test_mutation_during_both_curation_and_indexing(tmp_path, action):
    class DelayedVectors(MemoryVectors):
        def __init__(self):
            super().__init__(get_settings())
            self.entered, self.release = asyncio.Event(), asyncio.Event()

        async def put(self, memory, vector):
            self.entered.set()
            await self.release.wait()
            await super().put(memory, vector)

    curator, vectors, chat = BackgroundCurator(), DelayedVectors(), StreamingModel()
    async with chat_app(tmp_path, chat, memory_model=curator, embedding=Embedding(), vectors=vectors) as (client, app, _):
        async with app.router.lifespan_context(app):
            response = await client.patch("/api/admin/stores/1", json={
                "description": "社区烘焙店", "expected_description_revision": 1,
            })
            assert response.status_code == 200, response.text
            first = await turn(client, "以后分析先给结论，再列数据")
            assert (await settled(client, first["id"]))["status"] == "completed"
            await asyncio.wait_for(vectors.entered.wait(), 15)
            initial = (await client.get("/api/agent/1/memories")).json()
            item = initial["items"][0]
            curator.entered.clear()
            curator.release.clear()
            second = await turn(client, "以后回答简短")
            await asyncio.wait_for(curator.entered.wait(), 10)
            async with asyncio.timeout(5):
                if action in {"correct", "delete"}:
                    response = await client.request("PATCH" if action == "correct" else "DELETE",
                        f'/api/agent/1/memories/{item["id"]}', json={"expected_version": 1,
                        **({"content": "以后详细解释"} if action == "correct" else {})})
                elif action == "clear":
                    response = await client.post("/api/agent/1/memories/clear", json={"expected_revision": initial["revision"]})
                elif action == "reset":
                    response = await client.post("/api/agent/1/conversation/reset", json={"generation": 0})
                else:
                    response = await client.patch("/api/admin/stores/1", json={
                        "description": "" if action == "description_clear" else "洗车门店",
                        "expected_description_revision": 2,
                    })
                assert response.status_code in (200, 204), response.text
            curator.release.set()
            vectors.release.set()
            assert (await settled(client, second["id"]))["status"] == "stale"
            await wait_status(client, "available")
            curator.action = "reject"
            await save(client, "当前偏好？", generation=int(action == "reset"))
            expected = ([] if action in {"delete", "clear"} else
                        ["以后详细解释" if action == "correct" else item["content"]])
            assert [m["content"] for m in background(chat)["memories"]] == expected
            if action.startswith("description"):
                assert background(chat)["description"] == ("" if action == "description_clear" else "洗车门店")
            assert all(m["content"] != "以后回答简短" for m in (await client.get("/api/agent/1/memories")).json()["items"])


async def test_unconfigured_ai_does_not_block_existing_business(tmp_path, monkeypatch):
    for name in ("CHAT", "MEMORY", "EMBEDDING"):
        monkeypatch.setenv(f"AUTOLAVA_AGENT_{name}_MODEL", "")
        monkeypatch.setenv(f"AUTOLAVA_AGENT_{name}_API_KEY", "")
    monkeypatch.setenv("AUTOLAVA_AGENT_VECTOR_PATH", "")
    get_settings.cache_clear()
    # Use the real unconfigured provider: this must fail locally without a network call.
    async with chat_app(tmp_path, None) as (client, app, _):
        run = await save(client, "你好")
        assert run["status"] == "failed" and run["error_code"] == "model_not_configured"
        events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
        assert "event: failed" in events and "model_not_configured" in events
        from tests.api.test_agent_tools import save_day
        await save_day(client, "2026-10-01", 125)
        record = await client.get("/api/ledger/1/2026-10-01")
        assert record.status_code == 200 and record.json()["daily_revenue"] == 125
        assert (await client.get("/api/agent/1/memory-index")).json()["status"] == "unavailable"
