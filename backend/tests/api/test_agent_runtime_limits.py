import asyncio
from collections.abc import Sequence
from datetime import date
import json

import httpx
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentSystemSettings
from app.models.ledger import StoreDailyRecord
from app.services.agent_data_tools import AgentDataToolRegistry
from app.services.agent_model import ModelResponse, ModelToolCall
from app.services.agent_turn import AgentTurnRuntime


class ToolLimitAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(
        self,
        _messages: Sequence[dict[str, object]],
        _tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-performance",
                        name="load_skill",
                        arguments={"name": "business_performance"},
                    ),
                )
            )
        return ModelResponse(
            tool_calls=(
                ModelToolCall(
                    id=f"performance-{self.calls}",
                    name="business_performance_summary",
                    arguments={
                        "start": "2026-07-01",
                        "end": "2026-07-01",
                    },
                ),
            )
        )


class ToolStartDeadlineAdapter(ToolLimitAdapter):
    async def respond(
        self,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        response = await super().respond(messages, tools)
        if self.calls == 2:
            await asyncio.sleep(0.08)
        return response


class TransientModelAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(
        self,
        _messages: Sequence[dict[str, object]],
        _tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            raise httpx.ReadTimeout("secret upstream detail")
        return ModelResponse(content="重试后完成")


class DeterministicModelFailureAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(
        self,
        _messages: Sequence[dict[str, object]],
        _tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        self.calls += 1
        raise ValueError("secret invalid model payload")


class ToolTimeoutAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(
        self,
        messages: Sequence[dict[str, object]],
        _tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="load-performance",
                        name="load_skill",
                        arguments={"name": "business_performance"},
                    ),
                )
            )
        if self.calls == 2:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="timed-out-tool",
                        name="business_performance_summary",
                        arguments={
                            "start": "2026-07-01",
                            "end": "2026-07-01",
                        },
                    ),
                )
            )
        tool_payloads = [
            json.loads(str(message["content"]))
            for message in messages
            if message["role"] == "tool"
        ]
        assert tool_payloads[-1] == {
            "status": "failed",
            "error_category": "timeout",
        }
        return ModelResponse(content="数据工具超时，本轮没有可验证数值。")


class ToolRecoveryAdapter(ToolTimeoutAdapter):
    async def respond(
        self,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        if self.calls < 2:
            return await super().respond(messages, tools)
        self.calls += 1
        return ModelResponse(content="瞬时失败后已取得数据。")


class DeterministicToolFailureAdapter(ToolTimeoutAdapter):
    async def respond(
        self,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        if self.calls < 2:
            return await super().respond(messages, tools)
        self.calls += 1
        tool_payloads = [
            json.loads(str(message["content"]))
            for message in messages
            if message["role"] == "tool"
        ]
        assert tool_payloads[-1] == {
            "status": "failed",
            "error_category": "validation",
        }
        return ModelResponse(content="参数不符合数据工具要求，未取得数值。")


class UnavailableCalculationAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(
        self,
        _messages: Sequence[dict[str, object]],
        _tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        self.calls += 1
        if self.calls == 1:
            return ModelResponse(
                tool_calls=(
                    ModelToolCall(
                        id="divide-by-zero",
                        name="calculate",
                        arguments={
                            "steps": [
                                {
                                    "name": "ratio",
                                    "operation": "divide",
                                    "left": {
                                        "literal": "120",
                                        "source": "user",
                                    },
                                    "right": {
                                        "literal": "0",
                                        "source": "user",
                                    },
                                }
                            ]
                        },
                    ),
                )
            )
        return ModelResponse(content="该派生计算因除数为零而不可用。")


class TotalTimeoutAdapter(ToolLimitAdapter):
    async def respond(
        self,
        messages: Sequence[dict[str, object]],
        tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        if self.calls < 2:
            return await super().respond(messages, tools)
        self.calls += 1
        await asyncio.sleep(0.2)
        return ModelResponse(content="不应到达")


class NoEvidenceTimeoutAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(
        self,
        _messages: Sequence[dict[str, object]],
        _tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        self.calls += 1
        await asyncio.sleep(0.2)
        return ModelResponse(content="不应到达")


class LateLoadSkillAdapter:
    def __init__(self) -> None:
        self.calls = 0

    async def respond(
        self,
        _messages: Sequence[dict[str, object]],
        _tools: Sequence[dict[str, object]],
    ) -> ModelResponse:
        self.calls += 1
        await asyncio.sleep(0.08)
        return ModelResponse(
            tool_calls=(
                ModelToolCall(
                    id="late-load",
                    name="load_skill",
                    arguments={"name": "business_performance"},
                ),
            )
        )


class SlowDataTools(AgentDataToolRegistry):
    async def execute(self, *args, **kwargs):
        await asyncio.sleep(0.02)
        return await super().execute(*args, **kwargs)


class TransientDataTools(AgentDataToolRegistry):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.attempts = 0

    async def execute(self, *args, **kwargs):
        self.attempts += 1
        if self.attempts == 1:
            raise httpx.ReadTimeout("secret transient tool detail")
        return await super().execute(*args, **kwargs)


class DeterministicFailureDataTools(AgentDataToolRegistry):
    def __init__(self, session_factory) -> None:
        super().__init__(session_factory)
        self.attempts = 0

    async def execute(self, *_args, **_kwargs):
        self.attempts += 1
        raise ValueError("secret deterministic tool detail")


async def _login(client: AsyncClient, username: str) -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert response.status_code == 200


def _events(response_text: str) -> list[dict[str, object]]:
    return [json.loads(line) for line in response_text.splitlines() if line]


async def test_data_tool_limit_returns_and_persists_best_trusted_answer(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="tool-limit-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="工具上限门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 1),
                daily_revenue=120,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = ToolLimitAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=1,
        stop_new_tools_seconds=0.9,
        model_round_limit=8,
        data_tool_call_limit=1,
        data_tool_timeout_seconds=0.5,
        transient_retry_limit=1,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026-07-01 的营业额"},
    )

    events = _events(response.text)
    assert events[-1]["type"] == "completed"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation"
    )
    answer = restored.json()["messages"][-1]["content"]
    assert "台账营业额为 120欧元" in answer
    assert "数据工具次数上限" in answer
    assert adapter.calls == 3


async def test_model_round_limit_returns_successful_tool_evidence(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="round-limit-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="模型轮数上限门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 1),
                daily_revenue=120,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = ToolLimitAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=1,
        stop_new_tools_seconds=0.9,
        model_round_limit=2,
        data_tool_call_limit=12,
        data_tool_timeout_seconds=0.5,
        transient_retry_limit=1,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026-07-01 的营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation"
    )
    answer = restored.json()["messages"][-1]["content"]
    assert "台账营业额为 120欧元" in answer
    assert "模型轮数上限" in answer
    assert adapter.calls == 2


async def test_tool_start_deadline_stops_new_data_tools_with_safe_answer(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="tool-deadline-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="工具截止门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = ToolStartDeadlineAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=0.5,
        stop_new_tools_seconds=0.05,
        model_round_limit=8,
        data_tool_call_limit=12,
        data_tool_timeout_seconds=0.2,
        transient_retry_limit=1,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026-07-01 的营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation"
    )
    answer = restored.json()["messages"][-1]["content"]
    assert "停止发起新工具时限" in answer
    assert "未经验证" in answer
    assert adapter.calls == 2


async def test_tool_start_deadline_also_stops_skill_loading(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="skill-deadline-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="Skill 截止门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = LateLoadSkillAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=0.5,
        stop_new_tools_seconds=0.05,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation"
    )
    answer = restored.json()["messages"][-1]["content"]
    assert "停止发起新工具时限" in answer
    assert adapter.calls == 1


async def test_transient_model_failure_retries_once(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="model-retry-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="模型重试门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = TransientModelAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        transient_retry_limit=1,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    assert adapter.calls == 2


async def test_deterministic_model_failure_is_not_retried_or_exposed(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="model-no-retry-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="模型确定性失败门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = DeterministicModelFailureAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        transient_retry_limit=1,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    events = _events(response.text)
    assert events[-1] == {
        "type": "failed",
        "turn_id": events[-1]["turn_id"],
        "message": "Agent 本轮处理失败，请稍后重试",
    }
    assert "secret" not in response.text
    assert adapter.calls == 1


async def test_data_tool_timeout_has_safe_persisted_category(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="tool-timeout-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="工具超时门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = ToolTimeoutAdapter()
    app.state.agent_model_adapter = adapter
    def session_factory():
        return app.state.agent_session_factory()

    runtime = AgentTurnRuntime(
        session_factory,
        lambda: app.state.agent_model_adapter,
        data_tool_timeout_seconds=0.005,
        transient_retry_limit=1,
        data_tools=SlowDataTools(session_factory),
    )
    app.state.agent_turn_runtime = runtime
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation"
    )
    cards = restored.json()["latest_turn"]["investigation_cards"]
    assert cards == [
        {
            "operation": "汇总经营表现",
            "range_start": None,
            "range_end": None,
            "filters": [],
            "status": "failed",
            "error_category": "timeout",
        }
    ]
    assert "secret" not in response.text
    assert adapter.calls == 3


async def test_transient_data_tool_failure_retries_once(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="tool-retry-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="工具重试门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = ToolRecoveryAdapter()
    app.state.agent_model_adapter = adapter
    def session_factory():
        return app.state.agent_session_factory()

    data_tools = TransientDataTools(session_factory)
    runtime = AgentTurnRuntime(
        session_factory,
        lambda: app.state.agent_model_adapter,
        transient_retry_limit=1,
        data_tools=data_tools,
    )
    app.state.agent_turn_runtime = runtime
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    assert "secret" not in response.text
    assert data_tools.attempts == 2


async def test_deterministic_data_tool_failure_is_not_retried(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="tool-no-retry-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="工具确定性失败门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = DeterministicToolFailureAdapter()
    app.state.agent_model_adapter = adapter
    def session_factory():
        return app.state.agent_session_factory()

    data_tools = DeterministicFailureDataTools(session_factory)
    runtime = AgentTurnRuntime(
        session_factory,
        lambda: app.state.agent_model_adapter,
        transient_retry_limit=1,
        data_tools=data_tools,
    )
    app.state.agent_turn_runtime = runtime
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    assert "secret" not in response.text
    assert data_tools.attempts == 1


async def test_expected_calculation_unavailability_is_not_a_tool_failure(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="calculation-unavailable-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="计算不可用门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = UnavailableCalculationAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026-07-01 的营业额，并计算 120 除以 0"},
    )

    cards = [
        event["card"]
        for event in _events(response.text)
        if event["type"] == "investigation_card"
    ]
    assert cards == [
        {
            "operation": "完成派生计算",
            "range_start": None,
            "range_end": None,
            "filters": [],
            "status": "unavailable",
            "error_category": "expected_unavailable",
        }
    ]
    assert _events(response.text)[-1]["type"] == "completed"


async def test_total_timeout_returns_successful_current_turn_evidence(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="total-timeout-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="总时限门店")
    db_session.add_all(
        (
            AgentSystemSettings(enabled=True),
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 1),
                daily_revenue=120,
                is_open="营业",
                created_by=admin.id,
                updated_by=admin.id,
            ),
        )
    )
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = TotalTimeoutAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=0.12,
        stop_new_tools_seconds=0.09,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析 2026-07-01 的营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation"
    )
    answer = restored.json()["messages"][-1]["content"]
    assert "台账营业额为 120欧元" in answer
    assert "总轮次处理时限" in answer


async def test_total_timeout_without_evidence_returns_safe_limitation(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    admin = await user_factory(
        username="empty-total-timeout-admin",
        password="secret123",
        role="admin",
    )
    store = await store_factory(name="无证据总时限门店")
    db_session.add(AgentSystemSettings(enabled=True))
    await db_session.commit()
    store_id = store.id
    app = client._transport.app
    adapter = NoEvidenceTimeoutAdapter()
    app.state.agent_model_adapter = adapter
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=0.05,
        stop_new_tools_seconds=0.04,
    )
    await _login(client, admin.username)

    response = await client.post(
        f"/api/agent/stores/{store_id}/messages",
        json={"content": "分析营业额"},
    )

    assert _events(response.text)[-1]["type"] == "completed"
    restored = await client.get(
        f"/api/agent/stores/{store_id}/conversation"
    )
    answer = restored.json()["messages"][-1]["content"]
    assert "总轮次处理时限" in answer
    assert "未经验证" in answer
    assert restored.json()["latest_turn"]["status"] == "completed"
