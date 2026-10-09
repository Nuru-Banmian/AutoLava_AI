"""Execution adapters are injected, while authentication, runtime and SSE stay real."""

import asyncio
from uuid import uuid4

import pytest

from app.agents.assistant.graph import create_graph
from app.agents.registry import capabilities
from app.agents.tools.calculate import CalculateInput, calculate
from app.agents.tools.registry import Tool, ToolRegistry
from tests.api.test_agent_chat import chat_app, completed
from tests.api.test_agent_tools import ToolModel, ask


async def test_tool_receives_server_scope_and_remaining_budget(tmp_path):
    async def inspect(session, context, args):
        return {"user": context.scope.user_id, "store": context.scope.store_id,
                "run": context.run_id, "generation": context.generation,
                "budget": context.remaining_result_chars,
                "repository_available": context.results is not None}

    model = ToolModel([("calculate", {"expression": "1"}), "已读取服务端上下文。"])
    async with chat_app(tmp_path, model) as (client, app, _):
        skills, _ = capabilities()
        bound = ToolRegistry([Tool("calculate", "context probe", CalculateInput, inspect)]).bind(["calculate"])
        runner = app.state.agent_runner
        runner.graph = create_graph(model, runner.storage, runner.settings, agent_capabilities=(skills, bound))
        run = await ask(client)
        assert run["status"] == "completed", run
        observed = model.results[-1]
        assert observed == {"user": 1, "store": 1, "run": run["id"], "generation": 0,
                            "budget": observed["budget"], "repository_available": True}
        assert 0 < observed["budget"] <= 12000


@pytest.mark.parametrize("action", ["stop", "reset", "deactivate", "logout"])
async def test_results_finishing_after_execution_loses_authority_never_publish(tmp_path, action):
    entered, release = asyncio.Event(), asyncio.Event()

    async def delayed(session, context, args):
        entered.set()
        try:
            await release.wait()
        except asyncio.CancelledError:
            await release.wait()  # External operations can finish despite cancellation.
        return await calculate(session, context, args)

    model = ToolModel([("calculate", {"expression": "0.1+0.2"}), "迟到结果不得出现。"])
    async with chat_app(tmp_path, model) as (client, app, _):
        skills, _ = capabilities()
        bound = ToolRegistry([Tool("calculate", "delayed calculation", CalculateInput, delayed)]).bind(["calculate"])
        runner = app.state.agent_runner
        runner.graph = create_graph(model, runner.storage, runner.settings, agent_capabilities=(skills, bound))
        submitted = await client.post("/api/agent/1/messages", json={
            "request_id": uuid4().hex, "generation": 0, "content": "计算0.1+0.2",
        })
        run_id = submitted.json()["id"]
        await asyncio.wait_for(entered.wait(), 10)
        worker = runner.runs[run_id]
        if action == "stop":
            assert (await client.post(f"/api/agent/1/runs/{run_id}/stop")).status_code == 200
        elif action == "reset":
            assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
        elif action == "deactivate":
            assert (await client.patch("/api/admin/stores/1", json={"is_active": False})).status_code == 200
        else:
            assert (await client.post("/api/auth/logout")).status_code == 204
        release.set()
        await asyncio.wait_for(worker, 10)
        if action == "deactivate":
            assert (await client.get(f"/api/agent/1/runs/{run_id}/events")).status_code == 404
            assert len(model.calls) == 1
            return
        if action == "logout":
            assert (await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})).status_code == 200
        run = await completed(client, run_id)
        assert run["status"] == "failed"
        assert run["error_code"] == {"stop": "cancelled", "reset": "reset"}.get(action, "access_revoked")
        events = await client.get(f"/api/agent/1/runs/{run_id}/events")
        assert "event: tool" not in events.text and "event: completed" not in events.text
        assert len(model.calls) == 1
        history = (await client.get("/api/agent/1/conversation")).json()
        assert all("迟到结果" not in m["content"] for m in history["messages"])
