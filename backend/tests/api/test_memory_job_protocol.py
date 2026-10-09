"""Memory protocol regressions through HTTP and the external provider boundary."""
import json

import httpx
import pytest
import respx

from tests.api.test_agent_chat import StreamingModel, chat_app
from tests.api.test_memory_jobs import settled, turn
from tests.api.test_agent_memory import Curator, save


async def test_background_requires_proposal_tool_for_non_memory_turn(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_MEMORY_BASE_URL", "https://memory.test/v1")
    monkeypatch.setenv("AUTOLAVA_AGENT_MEMORY_API_KEY", "test-memory-key")
    monkeypatch.setenv("AUTOLAVA_AGENT_MEMORY_MODEL", "test-memory-model")

    def provider(request):
        payload = json.loads(request.content)
        required = {"type": "function", "function": {"name": "propose_memory"}}
        if payload.get("tool_choice") == required:
            delta = {"tool_calls": [{"index": 0, "id": "skip", "type": "function", "function": {
                "name": "propose_memory", "arguments": json.dumps({
                    "action": "reject", "content": "你好", "category": "preference",
                }, ensure_ascii=False),
            }}]}
            reason = "tool_calls"
        else:
            delta, reason = {"content": "这是一句问候，无需保存长期记忆。"}, "stop"
        body = "\n\n".join([
            "data: " + json.dumps({"choices": [{"delta": delta}]}, ensure_ascii=False),
            "data: " + json.dumps({"choices": [{"delta": {}, "finish_reason": reason}]}),
            "data: [DONE]", "",
        ])
        return httpx.Response(200, text=body)

    with respx.mock() as transport:
        route = transport.post("https://memory.test/v1/chat/completions").mock(side_effect=provider)
        async with chat_app(tmp_path, StreamingModel()) as (client, app, _):
            await app.state.agent_runner.jobs.start()
            run = await turn(client, "你好")
            job = await settled(client, run["id"])
            assert job["status"] == "completed", job
            assert job["result"] == {"status": "not_saved"}
            assert job["error_code"] is None and job["calls"] == 1
            assert (await client.get("/api/agent/1/memories")).json()["items"] == []
            assert len(route.calls) == 1


@pytest.mark.parametrize("proposal", [
    {"action": "save"},
    {"action": "save", "content": "以后回答简短"},
    {"action": "save", "category": "preference"},
])
async def test_missing_save_fields_remain_failed_without_creating_memories(tmp_path, proposal):
    async with chat_app(tmp_path, StreamingModel(), memory_model=Curator(proposal)) as (client, app, _):
        await app.state.agent_runner.jobs.start()
        run = await turn(client, "以后回答简短")
        job = await settled(client, run["id"])
        assert job["status"] == "failed" and job["error_code"] == "memory_invalid_proposal"
        assert (await client.get("/api/agent/1/memories")).json()["items"] == []


@pytest.mark.parametrize("explicit", [False, True], ids=["background", "explicit"])
async def test_reject_without_invented_memory_fields_is_not_a_failure(tmp_path, monkeypatch, explicit):
    monkeypatch.setenv("AUTOLAVA_AGENT_MEMORY_BASE_URL", "https://memory.test/v1")
    monkeypatch.setenv("AUTOLAVA_AGENT_MEMORY_API_KEY", "test-memory-key")
    monkeypatch.setenv("AUTOLAVA_AGENT_MEMORY_MODEL", "test-memory-model")
    body = "\n\n".join([
        "data: " + json.dumps({"choices": [{"delta": {"tool_calls": [{
            "index": 0, "id": "skip", "type": "function", "function": {
                "name": "propose_memory", "arguments": '{"action":"reject"}',
            },
        }]}}]}),
        'data: {"choices":[{"delta":{},"finish_reason":"tool_calls"}]}',
        "data: [DONE]", "",
    ])
    with respx.mock() as transport:
        transport.post("https://memory.test/v1/chat/completions").mock(
            return_value=httpx.Response(200, text=body))
        async with chat_app(tmp_path, StreamingModel()) as (client, app, _):
            if explicit:
                run = await save(client, "记住：今天先给结论")
                assert run["status"] == "completed", run
                assert "未保存" in run["output"] and "已保存" not in run["output"]
            else:
                await app.state.agent_runner.jobs.start()
                run = await turn(client, "你好")
                job = await settled(client, run["id"])
                assert job["status"] == "completed", job
                assert job["result"] == {"status": "not_saved"}
            assert (await client.get("/api/agent/1/memories")).json()["items"] == []
