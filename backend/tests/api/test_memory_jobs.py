"""T8 public contracts with migrated SQLite and controlled provider barriers."""
import asyncio
import json
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, text

from app.agents.providers.bailian import ModelFailure, ToolCall
from app.main import create_app
from app.core.config import get_settings
from tests.api.test_agent_chat import StreamingModel, chat_app, completed
from tests.api.test_agent_memory import save
from tests.api.test_agent_tools import background


class BackgroundCurator:
    model_name = "controlled-background-curator"

    def __init__(self):
        self.action = "save"
        self.target = {}
        self.content = None
        self.calls = []
        self.entered = asyncio.Event()
        self.release = asyncio.Event()
        self.release.set()
        self.failure = None

    async def stream_tools(self, messages, tools):
        snapshot = json.loads(messages[-1]["content"])
        self.calls.append(snapshot)
        self.entered.set()
        await self.release.wait()
        if self.failure:
            raise self.failure
        raw = snapshot["input"]
        content = raw.split("：", 1)[-1] if "mode" not in snapshot else raw
        yield ToolCall("proposal", "propose_memory", json.dumps({
            "action": self.action, "category": "preference", "content": self.content or content,
            **({"evidence": raw} if snapshot.get("mode") == "background" else {}), **self.target,
        }, ensure_ascii=False))


async def settled(client, run_id):
    async with asyncio.timeout(10):
        while True:
            response = await client.get("/api/agent/1/memory-jobs")
            assert response.status_code == 200, response.text
            job = next((j for j in response.json()["items"] if j["run_id"] == run_id), None)
            if job and job["status"] not in {"pending", "running"}:
                return job
            await asyncio.sleep(0.01)


async def turn(client, content):
    response = await client.post("/api/agent/1/messages", json={
        "content": content, "request_id": uuid4().hex, "generation": 0,
    })
    assert response.status_code == 202, response.text
    run = await completed(client, response.json()["id"])
    assert run["status"] == "completed", run
    events = await client.get(f'/api/agent/1/runs/{run["id"]}/events')
    assert "event: completed" in events.text
    return run


async def test_automatic_save_merge_update_candidates_and_scopes(tmp_path):
    curator = BackgroundCurator()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, _):
        await app.state.agent_runner.jobs.start()
        run = await turn(client, "以后分析先给结论，再列数据")
        assert (await settled(client, run["id"]))["result"]["status"] == "saved"
        item = (await client.get("/api/agent/1/memories")).json()["items"][0]
        assert item["sources"][0]["evidence"] == "以后分析先给结论，再列数据"
        curator.action = "duplicate"
        curator.content = item["content"]
        curator.target = {"target_id": item["id"], "target_version": item["version"]}
        run = await turn(client, "以后请先说结论再展示数据")
        await settled(client, run["id"])
        items = (await client.get("/api/agent/1/memories")).json()["items"]
        assert len(items) == 1 and len(items[0]["sources"]) == 2
        curator.action = "update"
        curator.content = None
        run = await turn(client, "更正：以后先列数据，再给结论")
        await settled(client, run["id"])
        updated = (await client.get("/api/agent/1/memories")).json()["items"][0]
        assert updated["version"] == 2 and updated["content"] == "更正：以后先列数据，再给结论"
        assert len(updated["sources"]) == 3 and updated["changes"][0]["previous_content"] == item["content"]

        for decision in ("confirm", "edit", "reject"):
            curator.action, curator.target = "infer", {}
            curator.content = f"推断偏好 {decision}"
            run = await turn(client, f"我在考虑另一种表达 {decision}")
            assert (await settled(client, run["id"]))["result"]["status"] == "pending_confirmation"
            candidate = next(m for m in (await client.get("/api/agent/1/memories")).json()["items"]
                             if m["content"] == curator.content)
            assert candidate["index_status"] == "not_scheduled"
            curator.action, curator.content = "reject", None
            probe = await turn(client, "你好")
            await settled(client, probe["id"])
            current_background = background(app.state.agent_runner.model.calls[-1])
            assert candidate["id"] not in [m["id"] for m in current_background["memories"]]
            path = f'/api/agent/1/memories/{candidate["id"]}'
            payload = {"expected_version": 1, **({"content": "以后回答简短"} if decision == "edit" else {})}
            operation = "reject" if decision == "reject" else "confirm"
            result = await client.post(f"{path}/{operation}", json=payload)
            assert result.status_code == (204 if operation == "reject" else 200), result.text
            assert (await client.post(f"{path}/{operation}", json=payload)).status_code == result.status_code
            if operation != "reject":
                assert result.json()["status"] == "active" and result.json()["version"] == 2
        assert (await client.get("/api/agent/2/memory-jobs")).json()["items"] == []
        assert (await client.post(path.replace("/agent/1/", "/agent/2/") + "/confirm", json={"expected_version": 1})).status_code == 404
        await client.post("/api/auth/login", json={"username": "user-2", "password": "Password123"})
        assert (await client.get("/api/agent/1/memory-jobs")).json()["items"] == []
        assert (await client.post(path + "/confirm", json={"expected_version": 1})).status_code == 404


@pytest.mark.parametrize("action", ["correct", "delete", "clear", "clear_empty", "reset", "description", "revoke"])
async def test_stale_background_work_never_restores_old_information(tmp_path, action):
    curator = BackgroundCurator()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, _):
        if action != "clear_empty":
            await save(client)
        initial = (await client.get("/api/agent/1/memories")).json()
        curator.entered.clear()
        curator.release.clear()
        await app.state.agent_runner.jobs.start()
        run = await turn(client, "以后回答简短")
        await asyncio.wait_for(curator.entered.wait(), 5)
        async with asyncio.timeout(5):
            if action in {"correct", "delete"}:
                item = initial["items"][0]
                response = await client.request("PATCH" if action == "correct" else "DELETE",
                    f'/api/agent/1/memories/{item["id"]}', json={"expected_version": 1,
                    **({"content": "以后详细解释"} if action == "correct" else {})})
            elif action.startswith("clear"):
                response = await client.post("/api/agent/1/memories/clear", json={"expected_revision": initial["revision"]})
            elif action == "reset":
                response = await client.post("/api/agent/1/conversation/reset", json={"generation": 0})
            else:
                response = await client.patch("/api/admin/stores/1", json=(
                    {"description": "社区烘焙店", "expected_description_revision": 1}
                    if action == "description" else {"is_active": False}))
            assert response.status_code in (200, 204), response.text
        curator.release.set()
        if action != "revoke":
            assert (await settled(client, run["id"]))["status"] == "stale"
            items = (await client.get("/api/agent/1/memories")).json()["items"]
            assert all(m["content"] != "以后回答简短" for m in items)
            assert (await client.get(f'/api/agent/1/runs/{run["id"]}')).json()["status"] == "completed"
        else:
            assert (await client.get("/api/agent/1/memory-jobs")).status_code == 404


async def test_failures_are_bounded_and_do_not_change_completed_answer(tmp_path):
    curator = BackgroundCurator()
    curator.failure = ModelFailure("model_unavailable", retryable=True)
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, _):
        await app.state.agent_runner.jobs.start()
        run = await turn(client, "以后回答简短")
        job = await settled(client, run["id"])
        assert job["status"] == "failed" and job["calls"] == 2 and job["failures"]
        assert job["error_code"] == "model_unavailable"
        assert (await client.get(f'/api/agent/1/runs/{run["id"]}')).json() == run
        assert (await client.get("/api/agent/1/memories")).json()["items"] == []


async def test_scope_revoke_and_immediate_regrant_fences_background_memory(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "user-3")
    get_settings.cache_clear()
    curator = BackgroundCurator()
    curator.release.clear()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, _):
        await app.state.agent_runner.jobs.start()
        run = await turn(client, "撤权前的偏好不得迟到写入")
        await asyncio.wait_for(curator.entered.wait(), 5)
        async with AsyncClient(transport=ASGITransport(app), base_url="http://testserver") as primary:
            await primary.post("/api/auth/login", json={"username": "user-3", "password": "Password123"})
            assert (await primary.patch("/api/admin/users/1", json={"store_ids": []})).status_code == 200
            assert (await primary.patch("/api/admin/users/1", json={"store_ids": [1, 2]})).status_code == 200
        assert (await client.get("/api/agent/1/memory-jobs")).status_code == 401
        curator.release.set()
        await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})
        assert (await settled(client, run["id"]))["status"] == "stale"
        assert (await client.get("/api/agent/1/memories")).json()["items"] == []
        fresh = await turn(client, "重新授权后可以记住的新偏好")
        assert (await settled(client, fresh["id"]))["status"] == "completed"
        assert [m["content"] for m in (await client.get("/api/agent/1/memories")).json()["items"]] == ["重新授权后可以记住的新偏好"]


async def test_queued_turn_rebases_normal_saves_but_not_user_mutations(tmp_path):
    curator = BackgroundCurator()
    curator.release.clear()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, _):
        await app.state.agent_runner.jobs.start()
        first = await turn(client, "以后回答先给结论")
        await asyncio.wait_for(curator.entered.wait(), 5)
        second = await turn(client, "以后分析多列数据")
        curator.release.set()
        assert (await settled(client, first["id"]))["status"] == "completed"
        assert (await settled(client, second["id"]))["status"] == "completed"
        items = (await client.get("/api/agent/1/memories")).json()["items"]
        assert {m["content"] for m in items} == {"以后回答先给结论", "以后分析多列数据"}
        assert len(curator.calls[-1]["conversation"]) >= 2


async def test_deleting_job_owner_does_not_block_other_scopes(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "user-1")
    get_settings.cache_clear()
    curator = BackgroundCurator()
    curator.release.clear()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, factory):
        @event.listens_for(factory.kw["bind"].sync_engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        async with factory() as session:
            await session.execute(text("PRAGMA foreign_keys=ON"))
        await app.state.agent_runner.jobs.start()
        await client.post("/api/auth/login", json={"username": "user-2", "password": "Password123"})
        await turn(client, "以后回答简短")
        await asyncio.wait_for(curator.entered.wait(), 5)
        await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})
        response = await client.delete("/api/admin/users/2")
        assert response.status_code == 204, response.text
        curator.release.set()
        run = await turn(client, "以后先给结论")
        assert (await settled(client, run["id"]))["status"] == "completed"


async def test_restart_recovers_pending_and_interrupted_jobs_without_replaying_commits(tmp_path):
    curator = BackgroundCurator()
    curator.release.clear()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, factory):
        await app.state.agent_runner.jobs.start()
        run = await turn(client, "以后回答简短")
        await asyncio.wait_for(curator.entered.wait(), 5)
        await app.state.agent_runner.close()
        curator.release.set()
        restarted = create_app(session_factory=factory, agent_model=StreamingModel(), memory_model=curator)
        restarted.dependency_overrides.update(app.dependency_overrides)
        await restarted.state.agent_runner.jobs.start()
        try:
            async with AsyncClient(transport=ASGITransport(restarted), base_url="http://testserver", cookies=client.cookies) as fresh:
                job = await settled(fresh, run["id"])
                assert job["status"] == "completed" and job["attempts"] == 2 and job["calls"] == 2
                assert job["failures"][0]["code"] == "interrupted"
                items = (await fresh.get("/api/agent/1/memories")).json()["items"]
                assert len(items) == 1 and len(items[0]["sources"]) == 1
                await restarted.state.agent_runner.jobs.close()
                await restarted.state.agent_runner.jobs.start()
                assert (await fresh.get("/api/agent/1/memories")).json()["items"] == items
                assert len(curator.calls) == 2
        finally:
            await restarted.state.agent_runner.close()


async def test_quotes_hypotheticals_temporary_and_inferred_content_are_not_active(tmp_path):
    curator = BackgroundCurator()
    async with chat_app(tmp_path, StreamingModel(), memory_model=curator) as (client, app, _):
        await app.state.agent_runner.jobs.start()
        for content in ("假设我以后喜欢简短回答", "引用：以后回答简短", "今天先给结论", "工具分析结果说以后回答简短"):
            run = await turn(client, content)
            await settled(client, run["id"])
        assert not any(m["status"] == "active" for m in (await client.get("/api/agent/1/memories")).json()["items"])
