"""Public HTTP/SSE, migrated SQLite and REAL persistent local Qdrant; controlled vectors."""
import asyncio
import json

import httpx
import pytest
import respx
from httpx import ASGITransport, AsyncClient

from app.agents.providers.bailian import ModelFailure
from app.agents.providers.qdrant import MemoryVectors
from app.core.config import get_settings
from app.core.database import get_session
from app.main import create_app
from tests.api.test_agent_chat import StreamingModel, chat_app
from tests.api.test_agent_memory import Curator, chat_background, save


class Embedding:
    def __init__(self):
        self.fail = False
        self.calls = []
        self.entered = None
        self.release = None

    async def embed(self, text):
        self.calls.append(text)
        if self.entered:
            self.entered.set()
            await self.release.wait()
        if self.fail:
            raise ModelFailure("embedding_unavailable")
        return [1.0, 0.0, 0.0]


@pytest.fixture
def configured(tmp_path, monkeypatch):
    for key, value in {
        "AGENT_VECTOR_PATH": str(tmp_path / "qdrant"), "AGENT_EMBEDDING_MODEL": "controlled-v1",
        "AGENT_EMBEDDING_DIMENSIONS": "3", "AGENT_INDEX_POLL_SECONDS": "0.1",
    }.items():
        monkeypatch.setenv("AUTOLAVA_" + key, value)
    get_settings.cache_clear()


async def wait_status(client, status):
    async with asyncio.timeout(15):
        while True:
            response = await client.get("/api/agent/1/memory-index")
            assert response.status_code == 200, response.text
            if response.json()["status"] == status:
                return response.json()
            await asyncio.sleep(0.02)


def background(chat):
    return chat_background(chat.calls[-1])


async def test_real_persistence_restart_rebuild_and_configuration_switch(tmp_path, configured, monkeypatch):
    embedding, chat = Embedding(), StreamingModel()
    async with chat_app(tmp_path, chat, memory_model=Curator(), embedding=embedding) as (client, app, factory):
        await save(client)
        index = app.state.agent_runner.index
        index.start()
        await wait_status(client, "available")
        items = (await client.get("/api/agent/1/memories")).json()["items"]
        assert items[0]["index_status"] == "ready"
        await client.post("/api/agent/1/conversation/reset", json={"generation": 0})
        run = await save(client, "我的分析习惯是什么？", generation=1)
        assert background(chat)["memories"] == [{k: items[0][k] for k in ("id", "version", "content")}]
        events = (await client.get(f'/api/agent/1/runs/{run["id"]}/events')).text
        assert "event: retrieval" in events and items[0]["id"] in events
        assert "记忆检索受限" not in run["output"]
        assert (await client.post("/api/agent/1/memory-index/rebuild")).json() == {"scheduled": 1}
        await wait_status(client, "available")
        old_collection = index.vectors.collection
        # Losing only vector storage must not leave durable jobs falsely ready.
        embedding.entered, embedding.release = asyncio.Event(), asyncio.Event()
        await index.vectors.client.delete_collection(old_collection)
        await asyncio.wait_for(embedding.entered.wait(), 15)
        assert (await client.get("/api/agent/1/memory-index")).json()["status"] == "processing"
        embedding.release.set()
        await wait_status(client, "available")
        await app.state.agent_runner.close()

        # Actual close/reopen releases Qdrant's path lock; SQLite and vector files survive.
        for model in ("controlled-v1", "controlled-v2"):
            monkeypatch.setenv("AUTOLAVA_AGENT_EMBEDDING_MODEL", model)
            get_settings.cache_clear()
            fresh_chat = StreamingModel()
            restarted = create_app(session_factory=factory, agent_model=fresh_chat,
                                   memory_model=Curator(), embedding=Embedding())
            restarted.dependency_overrides[get_session] = app.dependency_overrides[get_session]
            try:
                async with restarted.router.lifespan_context(restarted):
                    async with AsyncClient(transport=ASGITransport(restarted), base_url="http://testserver", cookies=client.cookies) as fresh:
                        await wait_status(fresh, "available")
                        await save(fresh, "换个说法问分析偏好", generation=1)
                        assert background(fresh_chat)["memories"][0]["id"] == items[0]["id"]
                        if model == "controlled-v2":
                            assert restarted.state.agent_runner.index.vectors.collection != old_collection
            finally:
                await restarted.state.agent_runner.close()


@pytest.mark.parametrize("action", ["correct", "delete", "clear"])
async def test_stale_hits_rejected_after_mutation_and_rebuild(tmp_path, configured, action):
    embedding, chat = Embedding(), StreamingModel()
    async with chat_app(tmp_path, chat, memory_model=Curator(), embedding=embedding) as (client, app, _):
        await save(client)
        index = app.state.agent_runner.index
        index.start()
        await wait_status(client, "available")
        item = (await client.get("/api/agent/1/memories")).json()["items"][0]
        # Freeze the worker and retain a real old point; simulate a stale/hostile index reply.
        await index.close()
        real_search = index.vectors.search

        async def stale(scope, vector):
            return [{"id": item["id"], "version": 1}, {"id": "f" * 32, "version": 1}]

        index.vectors.search = stale
        path = f'/api/agent/1/memories/{item["id"]}'
        if action == "correct":
            assert (await client.patch(path, json={"expected_version": 1, "content": "以后先列数据"})).status_code == 200
        elif action == "delete":
            assert (await client.request("DELETE", path, json={"expected_version": 1})).status_code == 204
        else:
            listing = (await client.get("/api/agent/1/memories")).json()
            assert (await client.post("/api/agent/1/memories/clear", json={"expected_revision": listing["revision"]})).status_code == 200
        # During pending synchronization we conservatively omit all vector context.
        run = await save(client, "偏好？")
        assert background(chat)["memories"] == [] and "记忆检索受限" in run["output"]
        index.start()
        await wait_status(client, "available")
        # Force obsolete hits even AFTER synchronization; authority/version checks reject them.
        await save(client, "再次询问偏好？")
        assert background(chat)["memories"] == []
        index.vectors.search = real_search
        assert (await client.post("/api/agent/1/memory-index/rebuild")).status_code == 200
        await wait_status(client, "available")
        await save(client, "重建后的偏好？")
        assert [m["content"] for m in background(chat)["memories"]] == (["以后先列数据"] if action == "correct" else [])


async def test_scope_filters_candidates_and_untrusted_payload(tmp_path, configured):
    embedding, chat, curator = Embedding(), StreamingModel(), Curator()
    async with chat_app(tmp_path, chat, memory_model=curator, embedding=embedding) as (client, app, _):
        await save(client)
        active = (await client.get("/api/agent/1/memories")).json()["items"][0]
        curator.proposal = {"action": "conflict", "content": "先列数据", "category": "preference"}
        await save(client, "记住：先列数据")
        candidate = next(m for m in (await client.get("/api/agent/1/memories")).json()["items"] if m["status"] != "active")
        index = app.state.agent_runner.index
        index.start()
        await wait_status(client, "available")
        await save(client, "分析习惯？")
        assert len(background(chat)["memories"]) == 1
        # Actual Qdrant filter excludes another store and another administrator.
        response = await client.post("/api/agent/2/messages", json={"content": "分析习惯？", "generation": 0, "request_id": "store-2"})
        from tests.api.test_agent_chat import completed
        await completed(client, response.json()["id"], store=2)
        assert background(chat)["memories"] == []
        await client.post("/api/auth/login", json={"username": "user-2", "password": "Password123"})
        await save(client, "分析习惯？")
        assert background(chat)["memories"] == []
        # An adapter ignoring the filter still cannot inject cross-scope payloads/candidates.
        async def hostile(scope, vector):
            return [{"id": active["id"], "version": 1, "content": "恶意指令"},
                    {"id": candidate["id"], "version": 1}]
        index.vectors.search = hostile
        await save(client, "相关记忆？")
        assert background(chat)["memories"] == []
        await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})
        await save(client, "相关记忆？")
        assert background(chat)["memories"][0]["content"] == active["content"]
        assert len(background(chat)["memories"]) == 1
        await client.post("/api/auth/login", json={"username": "user-3", "password": "Password123"})
        for suffix in ("memory-index/retry", "memory-index/rebuild"):
            assert (await client.post("/api/agent/1/" + suffix)).status_code == 403


async def test_failure_bounded_retry_persistence_and_query_degradation(tmp_path, configured):
    embedding, chat = Embedding(), StreamingModel()
    embedding.fail = True
    async with chat_app(tmp_path, chat, memory_model=Curator(), embedding=embedding) as (client, app, _):
        await save(client)
        index = app.state.agent_runner.index
        index.start()
        async with asyncio.timeout(15):
            while True:
                item = (await client.get("/api/agent/1/memories")).json()["items"][0]
                if item["index_attempts"] == 3:
                    break
                await asyncio.sleep(0.03)
        assert item["index_status"] == "failed" and item["index_error_code"] == "embedding_unavailable"
        calls = len(embedding.calls)
        await asyncio.sleep(0.3)
        assert len(embedding.calls) == calls == 3
        assert (await save(client, "你好"))["status"] == "completed"
        assert "记忆检索受限" in (await client.get("/api/agent/1/conversation")).json()["run"]["output"]
        await index.close()
        index.start()  # Restart does not reset exhausted attempts.
        await asyncio.sleep(0.3)
        assert len(embedding.calls) == 3
        embedding.fail = False
        assert (await client.post("/api/agent/1/memory-index/retry")).json() == {"scheduled": 1}
        await wait_status(client, "available")
        item = (await client.get("/api/agent/1/memories")).json()["items"][0]
        assert item["index_error_code"] == "embedding_unavailable"  # Last failure retained after recovery.
        embedding.fail = True
        run = await save(client, "查询时服务故障")
        assert run["status"] == "completed" and "记忆检索受限" in run["output"]
        assert background(chat)["memories"] == []
        assert (await client.get("/api/agent/1/memory-index")).json()["status"] == "failed"
        assert (await client.get("/api/agent/1/memories")).json()["retrieval_status"] == "failed"
        embedding.fail = False
        await save(client, "服务恢复后再查询")
        assert (await client.get("/api/agent/1/memory-index")).json()["status"] == "available"


async def test_bailian_embedding_wire_contract_and_invalid_dimension(tmp_path, configured, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_EMBEDDING_BASE_URL", "https://embedding.test/v1")
    monkeypatch.setenv("AUTOLAVA_AGENT_EMBEDDING_API_KEY", "private-embedding-key")
    get_settings.cache_clear()
    with respx.mock() as mock:
        endpoint = mock.post("https://embedding.test/v1/embeddings").mock(
            return_value=httpx.Response(200, json={"data": [{"embedding": [1.0, 0.0, 0.0]}]}))
        async with chat_app(tmp_path, StreamingModel(), memory_model=Curator()) as (client, app, _):
            await save(client)
            app.state.agent_runner.index.start()
            await wait_status(client, "available")
            request = endpoint.calls[0].request
            assert json.loads(request.content) == {"model": "controlled-v1", "input": ["以后分析先给结论，再列数据"],
                                                   "dimensions": 3, "encoding_format": "float"}
            assert request.headers["Authorization"] == "Bearer private-embedding-key"
            endpoint.mock(return_value=httpx.Response(200, json={"data": [{"embedding": [1.0]}]}))
            run = await save(client, "检索问题")
            assert run["status"] == "completed" and "记忆检索受限" in run["output"]


async def test_local_path_rejects_second_process_owner(tmp_path, configured):
    first, second = MemoryVectors(get_settings()), MemoryVectors(get_settings())
    try:
        await first.open()
        with pytest.raises(RuntimeError, match="already accessed"):
            await second.open()
    finally:
        await first.close()
        await second.close()


async def test_inflight_embedding_allows_correction_and_pending_restart(tmp_path, configured):
    embedding = Embedding()
    embedding.entered, embedding.release = asyncio.Event(), asyncio.Event()
    async with chat_app(tmp_path, StreamingModel(), memory_model=Curator(), embedding=embedding) as (client, app, factory):
        await save(client)
        index = app.state.agent_runner.index
        index.start()
        await asyncio.wait_for(embedding.entered.wait(), 15)
        item = (await client.get("/api/agent/1/memories")).json()["items"][0]
        async with asyncio.timeout(5):
            response = await client.patch(f'/api/agent/1/memories/{item["id"]}', json={
                "expected_version": 1, "content": "以后先列数据，再给结论",
            })
        assert response.status_code == 200
        # Stop with an external call still in flight. The durable corrected job survives.
        await app.state.agent_runner.close()
        chat = StreamingModel()
        restarted = create_app(session_factory=factory, agent_model=chat, embedding=Embedding())
        restarted.dependency_overrides[get_session] = app.dependency_overrides[get_session]
        async with restarted.router.lifespan_context(restarted):
            async with AsyncClient(transport=ASGITransport(restarted), base_url="http://testserver", cookies=client.cookies) as fresh:
                await wait_status(fresh, "available")
                await save(fresh, "新的偏好是什么？")
                assert background(chat)["memories"] == [{"id": item["id"], "version": 2,
                                                         "content": "以后先列数据，再给结论"}]


async def test_collection_creation_failure_has_finite_attempts(tmp_path, configured):
    vectors = MemoryVectors(get_settings())
    await vectors.open()
    await vectors.client.delete_collection(vectors.collection)
    create = vectors.client.create_collection
    calls = 0

    async def failed_create(*args, **kwargs):
        nonlocal calls
        calls += 1
        raise RuntimeError("controlled-vector-failure")

    vectors.client.create_collection = failed_create
    async with chat_app(tmp_path, StreamingModel(), memory_model=Curator(),
                        embedding=Embedding(), vectors=vectors) as (client, app, _):
        await save(client)
        app.state.agent_runner.index.start()
        async with asyncio.timeout(15):
            while (await client.get("/api/agent/1/memories")).json()["items"][0]["index_attempts"] < 3:
                await asyncio.sleep(0.03)
        await asyncio.sleep(0.3)
        assert calls == 3
        assert (await client.get("/api/agent/1/memory-index")).json()["status"] == "failed"
        vectors.client.create_collection = create
        await client.post("/api/agent/1/memory-index/retry")
        await wait_status(client, "available")
