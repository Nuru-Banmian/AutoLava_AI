from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.conversation import ConversationState
from app.agent.contracts import ModelMessage
from app.agent.native import (
    FakeNativeToolModel,
    NativeToolAccessDenied,
    NativeToolAgentService,
)
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags


class FailingEvidenceCollector:
    calls = 0

    async def collect(self, plan, context):
        del plan, context
        self.calls += 1
        raise RuntimeError("database details must not reach the model")


class RecordingEvidenceCollector:
    def __init__(self) -> None:
        self.calls = []

    async def collect(self, plan, context):
        self.calls.append((plan, context))
        raise AssertionError("unauthorized tool calls must not reach business evidence")


class DenyingScopeResolver:
    calls = 0

    async def refresh(self, context):
        del context
        self.calls += 1
        raise NativeToolAccessDenied("runtime scope is no longer authorized")


class PassthroughScopeResolver:
    calls = 0

    async def refresh(self, context):
        self.calls += 1
        return context


class DenyExecutionScopeResolver:
    calls = 0

    async def refresh(self, context):
        self.calls += 1
        if self.calls == 1:
            return context
        raise NativeToolAccessDenied("runtime scope is no longer authorized")


def _runtime_context(
    *,
    agent_enabled: bool = True,
    store_timezone: str = "Europe/Rome",
) -> RuntimeContext:
    return RuntimeContext(
        user_id=1,
        store_id=2,
        role="admin",
        store_timezone=store_timezone,
        features=RuntimeFeatureFlags(
            agent_enabled=agent_enabled,
            company_settlement_enabled=True,
            income_items_enabled=True,
            wash_count_enabled=True,
        ),
    )


async def test_native_tool_failure_is_returned_to_the_model_in_the_unified_envelope() -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "查询。"},
                "tool_calls": [
                    {
                        "id": "failed-call",
                        "name": "monthly_total_revenue",
                        "arguments": {"year": 2026, "month": 7},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "经营查询暂时不可用，目前无法确认月度总收入。",
                },
                "signal": "end",
            },
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=FailingEvidenceCollector(),
        scope_resolver=PassthroughScopeResolver(),
        now=lambda: datetime(2026, 7, 26, 10, 0, tzinfo=timezone.utc),
    )

    result = await service.run(
        RuntimeContext(
            user_id=1,
            store_id=2,
            role="admin",
            store_timezone="Europe/Rome",
            features=RuntimeFeatureFlags(
                agent_enabled=True,
                company_settlement_enabled=True,
                income_items_enabled=True,
                wash_count_enabled=True,
            ),
        ),
        ConversationState(),
        [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
    )

    tool_result = model.calls[1].items[-1].tool_result
    assert tool_result is not None
    assert tool_result.evidence.failure.model_dump() == {
        "status": "failed",
        "category": "business_query_unavailable",
        "message": "经营查询暂时不可用",
    }
    assert tool_result.evidence.facts == {}
    assert tool_result.evidence.scope.id == 2
    assert "database details" not in tool_result.model_dump_json()
    assert result.evidence is None
    assert result.turn.content == "经营查询暂时不可用，目前无法确认月度总收入。"


async def test_native_loop_does_not_let_the_model_guess_an_unconfirmed_month() -> None:
    collector = FailingEvidenceCollector()
    model = FakeNativeToolModel(turns=[])
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=PassthroughScopeResolver(),
    )

    result = await service.run(
        RuntimeContext(
            user_id=1,
            store_id=2,
            role="admin",
            store_timezone="Europe/Rome",
            features=RuntimeFeatureFlags(
                agent_enabled=True,
                company_settlement_enabled=True,
                income_items_enabled=True,
                wash_count_enabled=True,
            ),
        ),
        ConversationState(),
        [ModelMessage(role="user", content="最近的月度总收入是多少？")],
    )

    assert result.turn.route == "clarify"
    assert result.turn.content == "请提供要查询的准确自然月，例如“2026 年 7 月”。"
    assert model.calls == []
    assert collector.calls == 0


async def test_native_tool_catalog_rejects_a_disabled_runtime_before_model_execution() -> None:
    model = FakeNativeToolModel(turns=[])
    collector = RecordingEvidenceCollector()
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=PassthroughScopeResolver(),
    )

    with pytest.raises(NativeToolAccessDenied, match="not available"):
        await service.run(
            _runtime_context(agent_enabled=False),
            ConversationState(),
            [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
        )

    assert model.calls == []
    assert collector.calls == []


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("read_database", {"sql": "SELECT * FROM users"}),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "table": "users"},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "field": "password_hash"},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "expression": "sum(amount)"},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "path": "/etc/passwd"},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "url": "https://example.test"},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "limit": 1_000_000},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "user_id": 999},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "store_id": 999},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "role": "final_admin"},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "store_timezone": "UTC"},
        ),
        (
            "monthly_total_revenue",
            {"year": 2026, "month": 7, "features": {"agent_enabled": True}},
        ),
        ("monthly_total_revenue", {"year": 2026, "month": 13}),
    ],
)
async def test_native_tool_contract_fails_closed_for_unpublished_or_unbounded_calls(
    name: str,
    arguments: dict[str, object],
) -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "尝试调用工具。"},
                "tool_calls": [
                    {
                        "id": "forged-call",
                        "name": name,
                        "arguments": arguments,
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {"role": "assistant", "content": "不应重试。"},
                "signal": "end",
            },
        ]
    )
    collector = RecordingEvidenceCollector()
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=PassthroughScopeResolver(),
    )

    with pytest.raises(NativeToolAccessDenied, match="not authorized"):
        await service.run(
            _runtime_context(),
            ConversationState(),
            [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
        )

    assert len(model.calls) == 1
    assert collector.calls == []


async def test_native_tool_execution_reauthorizes_after_the_model_selects_a_tool() -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "查询。"},
                "tool_calls": [
                    {
                        "id": "revoked-call",
                        "name": "monthly_total_revenue",
                        "arguments": {"year": 2026, "month": 7},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {"role": "assistant", "content": "不应重试。"},
                "signal": "end",
            },
        ]
    )
    collector = RecordingEvidenceCollector()
    resolver = DenyExecutionScopeResolver()
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=resolver,
    )

    with pytest.raises(NativeToolAccessDenied, match="no longer authorized"):
        await service.run(
            _runtime_context(),
            ConversationState(),
            [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
        )

    assert resolver.calls == 2
    assert len(model.calls) == 1
    assert collector.calls == []


async def test_native_tool_catalog_reauthorizes_before_the_model_sees_tools() -> None:
    model = FakeNativeToolModel(turns=[])
    collector = RecordingEvidenceCollector()
    resolver = DenyingScopeResolver()
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=resolver,
    )

    with pytest.raises(NativeToolAccessDenied, match="no longer authorized"):
        await service.run(
            _runtime_context(),
            ConversationState(),
            [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
        )

    assert resolver.calls == 1
    assert model.calls == []
    assert collector.calls == []


async def test_native_tool_catalog_rejects_an_invalid_backend_timezone_before_model() -> None:
    model = FakeNativeToolModel(turns=[])
    collector = RecordingEvidenceCollector()
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=PassthroughScopeResolver(),
    )

    with pytest.raises(NativeToolAccessDenied, match="not available"):
        await service.run(
            _runtime_context(store_timezone="not/a-timezone"),
            ConversationState(),
            [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
        )

    assert model.calls == []
    assert collector.calls == []


@pytest.mark.parametrize(
    "feature",
    [
        "company_settlement_enabled",
        "income_items_enabled",
        "wash_count_enabled",
    ],
)
async def test_monthly_revenue_policy_stays_available_when_optional_store_features_are_off(
    feature: str,
) -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "无需查询。"},
                "signal": "end",
            }
        ]
    )
    context = _runtime_context()
    context = context.model_copy(
        update={"features": context.features.model_copy(update={feature: False})}
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=RecordingEvidenceCollector(),
        scope_resolver=PassthroughScopeResolver(),
    )

    await service.run(
        context,
        ConversationState(),
        [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
    )

    assert [tool.name for tool in model.calls[0].tools] == ["monthly_total_revenue"]


async def test_native_business_query_reauthorizes_inside_its_sqlite_snapshot(
    db_session: AsyncSession,
) -> None:
    @asynccontextmanager
    async def session_factory():
        yield db_session

    authorization_sessions = []

    async def deny_inside_snapshot(session, context):
        del context
        authorization_sessions.append(session)
        raise NativeToolAccessDenied("runtime scope is no longer authorized")

    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "查询。"},
                "tool_calls": [
                    {
                        "id": "atomic-call",
                        "name": "monthly_total_revenue",
                        "arguments": {"year": 2026, "month": 7},
                    }
                ],
                "signal": "continue",
            }
        ]
    )
    collector = BusinessEvidenceCollector(
        session_factory,
        scope_authorizer=deny_inside_snapshot,
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=PassthroughScopeResolver(),
    )

    with pytest.raises(NativeToolAccessDenied, match="no longer authorized"):
        await service.run(
            _runtime_context(),
            ConversationState(),
            [ModelMessage(role="user", content="2026 年 7 月收入是多少？")],
        )

    assert authorization_sessions == [db_session]
    assert len(model.calls) == 1
