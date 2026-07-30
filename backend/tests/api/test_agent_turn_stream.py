import asyncio
from collections.abc import AsyncIterator, Sequence
import json

import httpx
from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import (
    AgentMessage,
    AgentSystemSettings,
    AgentTurn,
)
from app.services.agent_turn import AgentTurnRuntime


class StreamingModelAdapter:
    def __init__(self, *chunks: str) -> None:
        self.chunks = chunks
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.calls: list[Sequence[dict[str, str]]] = []

    async def complete(self, messages: Sequence[dict[str, str]]) -> str:
        return "".join([chunk async for chunk in self.stream(messages)])

    async def stream(
        self,
        messages: Sequence[dict[str, str]],
    ) -> AsyncIterator[str]:
        self.calls.append(messages)
        self.started.set()
        await self.release.wait()
        for chunk in self.chunks:
            yield chunk


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200


def _json_lines(response_text: str) -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in response_text.splitlines()
        if line.strip()
    ]


async def test_json_lines_turn_stream_persists_completion_for_reload(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="turn-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="流式门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = StreamingModelAdapter("本月", "经营稳定。")
    adapter.release.set()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析本月经营情况"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert response.headers["x-accel-buffering"] == "no"
    assert response.headers["cache-control"] == "no-cache"
    events = _json_lines(response.text)
    assert [event["type"] for event in events] == [
        "started",
        "phase",
        "phase",
        "phase",
        "answer_delta",
        "answer_delta",
        "completed",
    ]
    assert [event.get("phase") for event in events if event["type"] == "phase"] == [
        "querying_data",
        "processing_data",
        "preparing_answer",
    ]
    assert [
        event["delta"]
        for event in events
        if event["type"] == "answer_delta"
    ] == ["本月", "经营稳定。"]

    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    assert restored.status_code == 200
    assert restored.json()["latest_turn"]["status"] == "completed"
    assert restored.json()["latest_turn"]["error_message"] is None
    assert [
        (message["role"], message["content"])
        for message in restored.json()["messages"]
    ] == [
        ("user", "分析本月经营情况"),
        ("assistant", "本月经营稳定。"),
    ]


async def test_active_turn_rejects_same_conversation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="parallel-admin",
        password="secret123",
        role="admin",
    )
    first_store = await store_factory(name="一店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    first_store_id = first_store.id
    adapter = StreamingModelAdapter("完成")
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    first_response = asyncio.create_task(
        client.post(
            f"/api/agent/stores/{first_store_id}/messages",
            json={"content": "分析营业额"},
        )
    )
    await asyncio.wait_for(adapter.started.wait(), timeout=1)

    duplicate = await client.post(
        f"/api/agent/stores/{first_store_id}/messages",
        json={"content": "再分析一次营业额"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "当前 Agent 会话已有进行中的轮次"

    adapter.release.set()
    assert (await first_response).status_code == 200


async def test_failed_turn_has_explicit_event_and_safe_persisted_state(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    class FailingAdapter:
        async def complete(self, _messages) -> str:
            raise RuntimeError("provider secret detail")

    admin = await user_factory(
        username="failure-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="失败门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    client._transport.app.state.agent_model_adapter = FailingAdapter()
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析本月营业额"},
    )

    events = _json_lines(response.text)
    assert events[-1]["type"] == "failed"
    assert events[-1]["message"] == "Agent 本轮处理失败，请稍后重试"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    assert restored.json()["latest_turn"]["status"] == "failed"
    assert restored.json()["latest_turn"]["error_message"] == (
        "Agent 本轮处理失败，请稍后重试"
    )
    assert [message["role"] for message in restored.json()["messages"]] == [
        "user",
    ]


async def test_complete_adapter_cannot_stream_or_persist_untrusted_values(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    class UntrustedCompleteAdapter:
        async def complete(self, _messages) -> str:
            return "台账营业额为 999 欧元。"

    admin = await user_factory(
        username="untrusted-complete-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="完整回答安全门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    client._transport.app.state.agent_model_adapter = (
        UntrustedCompleteAdapter()
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析本月营业额"},
    )

    events = _json_lines(response.text)
    assert all(
        "999" not in str(event.get("delta", ""))
        for event in events
        if event["type"] == "answer_delta"
    )
    assert events[-1]["type"] == "failed"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    assert all(
        "999" not in message["content"]
        for message in restored.json()["messages"]
    )


async def test_closing_live_event_subscription_does_not_cancel_background_turn(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="disconnect-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="断线门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    user_id = admin.id
    store_id = store.id
    adapter = StreamingModelAdapter("断线后仍然完成")
    app = client._transport.app
    app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    events = await app.state.agent_turn_runtime.start(
        user_id=user_id,
        store_id=store_id,
        content="分析营业额",
    )
    first_event = await anext(events)
    await events.aclose()
    adapter.release.set()

    assert json.loads(first_event)["type"] == "started"
    await asyncio.sleep(0.1)
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    assert restored.json()["latest_turn"]["status"] == "completed"
    assert restored.json()["messages"][-1]["content"] == "断线后仍然完成"


async def test_transient_model_failure_retries_once_before_streaming(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    class RetryAdapter:
        def __init__(self) -> None:
            self.calls = 0

        async def complete(self, _messages) -> str:
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("temporary timeout")
            return "重试后完成"

    admin = await user_factory(
        username="retry-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="重试门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    adapter = RetryAdapter()
    client._transport.app.state.agent_model_adapter = adapter
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    assert _json_lines(response.text)[-1]["type"] == "completed"
    assert adapter.calls == 2
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    assert restored.json()["messages"][-1]["content"] == "重试后完成"


async def test_turn_timeout_finishes_with_already_streamed_partial_answer(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    class PartialAdapter:
        async def stream(self, _messages) -> AsyncIterator[str]:
            yield "当前可用结果"
            await asyncio.Event().wait()

    admin = await user_factory(
        username="timeout-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="时限门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    app.state.agent_model_adapter = PartialAdapter()
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=0.1,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    events = _json_lines(response.text)
    assert events[-1] == {
        "type": "completed",
        "turn_id": events[-1]["turn_id"],
        "partial": True,
    }
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    assert restored.json()["messages"][-1]["content"] == (
        "当前可用结果\n\n（本轮已达到处理时限，以上为当前可用结果。）"
    )


async def test_startup_recovery_marks_running_turn_interrupted_without_resume(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="restart-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="重启门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    await _login(client, admin.username)
    conversation = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    conversation_id = conversation.json()["conversation_id"]
    user_message = AgentMessage(
        conversation_id=conversation_id,
        role="user",
        content="分析营业额",
    )
    db_session.add(user_message)
    await db_session.flush()
    db_session.add(
        AgentTurn(
            conversation_id=conversation_id,
            user_message_id=user_message.id,
            status="running",
        )
    )
    await db_session.commit()

    await client._transport.app.state.agent_turn_runtime.recover_interrupted_turns()

    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation",
    )
    assert restored.json()["latest_turn"]["status"] == "interrupted"
    assert restored.json()["latest_turn"]["error_message"] == (
        "后端进程已重新启动，本轮未自动继续"
    )
    assert [message["role"] for message in restored.json()["messages"]] == [
        "user",
    ]


async def test_start_timeout_releases_conversation_slot_for_retry(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    admin = await user_factory(
        username="start-timeout-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="启动超时门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = StreamingModelAdapter("重试成功")
    adapter.release.set()
    app.state.agent_model_adapter = adapter
    runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=0.01,
    )
    app.state.agent_turn_runtime = runtime
    original_persist_start = runtime._persist_start

    async def blocked_start(**_kwargs):
        await asyncio.Event().wait()

    monkeypatch.setattr(runtime, "_persist_start", blocked_start)
    await _login(client, admin.username)

    timed_out = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )
    monkeypatch.setattr(runtime, "_persist_start", original_persist_start)
    runtime._turn_timeout_seconds = 1
    retried = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    assert timed_out.status_code == 503
    assert timed_out.json()["detail"] == "Agent 本轮启动超时，请稍后重试"
    assert retried.status_code == 200
    assert _json_lines(retried.text)[-1]["type"] == "completed"
