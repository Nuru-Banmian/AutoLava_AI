import asyncio
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone

import pytest

from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.conversation import ConversationState
from app.agent.contracts import (
    ConfirmedSettlementIncomeResult,
    CurrentStoreScope,
    DailyLedgerRevenueResult,
    EvidenceBundle,
    EvidenceCoverage,
    EvidenceMetric,
    EvidencePeriodResult,
    ModelMessage,
    MonthlyTotalRevenueResult,
    OperatingDaysResult,
)
from app.agent.native import (
    FakeNativeToolModel,
    NativeModelTurn,
    NativeToolAccessDenied,
    NativeToolAgentService,
    NativeToolCall,
    NativeTranscriptItem,
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


def _evidence(metric: EvidenceMetric, value: int) -> EvidenceBundle:
    result_by_metric = {
        EvidenceMetric.MONTHLY_TOTAL_REVENUE: MonthlyTotalRevenueResult(
            daily_ledger_revenue=value,
            confirmed_settlement_income=0,
            monthly_total_revenue=value,
        ),
        EvidenceMetric.DAILY_LEDGER_REVENUE: DailyLedgerRevenueResult(daily_ledger_revenue=value),
        EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME: ConfirmedSettlementIncomeResult(
            confirmed_settlement_income=value
        ),
        EvidenceMetric.OPERATING_DAYS: OperatingDaysResult(operating_days=value),
    }
    version_by_metric = {
        EvidenceMetric.MONTHLY_TOTAL_REVENUE: "monthly_total_revenue.v1",
        EvidenceMetric.DAILY_LEDGER_REVENUE: "daily_ledger_revenue.v1",
        EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME: "confirmed_settlement_income.v1",
        EvidenceMetric.OPERATING_DAYS: "operating_days.v1",
    }
    unit_by_metric = {
        EvidenceMetric.MONTHLY_TOTAL_REVENUE: "EUR",
        EvidenceMetric.DAILY_LEDGER_REVENUE: "EUR",
        EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME: "EUR",
        EvidenceMetric.OPERATING_DAYS: "day",
    }
    return EvidenceBundle(
        status="ok",
        current_store=CurrentStoreScope(id=2),
        period=EvidencePeriodResult(start=date(2026, 7, 1), end=date(2026, 7, 31)),
        metric=metric,
        unit=unit_by_metric[metric],
        calculation_version=version_by_metric[metric],
        result=result_by_metric[metric],
        coverage=EvidenceCoverage(calendar_dates=31, recorded_dates=31),
        summary=f"{metric.value}={value}",
    )


class MetricEvidenceCollector:
    def __init__(self, *, daily_revenue: int = 100) -> None:
        self.daily_revenue = daily_revenue
        self.metrics: list[EvidenceMetric] = []

    async def collect(self, plan, context):
        del context
        metric = plan.requests[0].metric
        self.metrics.append(metric)
        values = {
            EvidenceMetric.DAILY_LEDGER_REVENUE: self.daily_revenue,
            EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME: 40,
            EvidenceMetric.OPERATING_DAYS: 20,
            EvidenceMetric.MONTHLY_TOTAL_REVENUE: self.daily_revenue + 40,
        }
        return _evidence(metric, values[metric])


class EvidenceAdaptiveModel:
    def __init__(self) -> None:
        self.selected_tools: list[str] = []

    async def next_turn(self, items, *, tools):
        del tools
        results = [item.tool_result for item in items if item.tool_result is not None]
        if not results:
            selected = "daily_ledger_revenue"
        elif len(results) == 1:
            daily_revenue = results[0].evidence.facts["daily_ledger_revenue"]
            selected = "operating_days" if daily_revenue < 1_000 else "confirmed_settlement_income"
        else:
            return NativeModelTurn(
                message={"role": "assistant", "content": "证据已足够，结束调查。"},
                signal="end",
            )
        self.selected_tools.append(selected)
        return NativeModelTurn(
            message={"role": "assistant", "content": f"继续检验 {selected}。"},
            tool_calls=[
                NativeToolCall(
                    id=f"call-{len(results) + 1}",
                    name=selected,
                    arguments={"year": 2026, "month": 7},
                )
            ],
            signal="continue",
        )


@pytest.mark.parametrize(
    ("daily_revenue", "expected_follow_up"),
    [(600, "operating_days"), (1_600, "confirmed_settlement_income")],
)
async def test_native_investigation_chooses_follow_up_from_returned_evidence(
    daily_revenue: int,
    expected_follow_up: str,
) -> None:
    model = EvidenceAdaptiveModel()
    collector = MetricEvidenceCollector(daily_revenue=daily_revenue)
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=PassthroughScopeResolver(),
    )

    result = await service.run(
        _runtime_context(),
        ConversationState(),
        [ModelMessage(role="user", content="调查 2026 年 7 月的经营表现。")],
    )

    assert model.selected_tools == ["daily_ledger_revenue", expected_follow_up]
    assert collector.metrics == [
        EvidenceMetric.DAILY_LEDGER_REVENUE,
        EvidenceMetric(expected_follow_up),
    ]
    assert result.turn.content == "证据已足够，结束调查。"


class ConcurrentEvidenceCollector(MetricEvidenceCollector):
    def __init__(self) -> None:
        super().__init__()
        self.active = 0
        self.max_active = 0
        self.started = 0
        self.both_started = asyncio.Event()

    async def collect(self, plan, context):
        self.active += 1
        self.started += 1
        self.max_active = max(self.max_active, self.active)
        if self.started == 2:
            self.both_started.set()
        await self.both_started.wait()
        try:
            return await super().collect(plan, context)
        finally:
            self.active -= 1


async def test_native_investigation_runs_independent_tool_calls_in_parallel() -> None:
    collector = ConcurrentEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "并行核对构成。"},
                "tool_calls": [
                    {
                        "id": "daily",
                        "name": "daily_ledger_revenue",
                        "arguments": {"year": 2026, "month": 7},
                    },
                    {
                        "id": "settlement",
                        "name": "confirmed_settlement_income",
                        "arguments": {"year": 2026, "month": 7},
                    },
                ],
                "signal": "continue",
            },
            {
                "message": {"role": "assistant", "content": "核对完成。"},
                "signal": "end",
            },
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=PassthroughScopeResolver(),
    )

    result = await asyncio.wait_for(
        service.run(
            _runtime_context(),
            ConversationState(),
            [ModelMessage(role="user", content="调查 2026 年 7 月的收入构成。")],
        ),
        timeout=1,
    )

    assert collector.max_active == 2
    assert [
        item.tool_result.call_id for item in model.calls[1].items if item.tool_result is not None
    ] == ["daily", "settlement"]
    assert result.turn.content == "核对完成。"


async def test_native_investigation_closes_on_an_invalid_parallel_tool_contract() -> None:
    collector = MetricEvidenceCollector()
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "并行核对。"},
                "tool_calls": [
                    {
                        "id": "invalid",
                        "name": "daily_ledger_revenue",
                        "arguments": {"year": 2026, "month": 13},
                    },
                    {
                        "id": "valid",
                        "name": "operating_days",
                        "arguments": {"year": 2026, "month": 7},
                    },
                ],
                "signal": "continue",
            },
            {
                "message": {"role": "assistant", "content": "保留有效证据后结束。"},
                "signal": "end",
            },
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=collector,
        scope_resolver=PassthroughScopeResolver(),
    )

    with pytest.raises(NativeToolAccessDenied, match="not authorized"):
        await service.run(
            _runtime_context(),
            ConversationState(),
            [ModelMessage(role="user", content="调查 2026 年 7 月的经营表现。")],
        )

    assert len(model.calls) == 1


async def test_native_investigation_carries_analysis_hypotheses_between_turns() -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "先检验经营日是否偏少。"},
                "hypotheses": [
                    {
                        "statement": "收入偏低可能与经营日偏少相关",
                        "status": "testing",
                        "evidence_references": [],
                    }
                ],
                "tool_calls": [
                    {
                        "id": "days",
                        "name": "operating_days",
                        "arguments": {"year": 2026, "month": 7},
                    }
                ],
                "signal": "continue",
            },
            {
                "message": {"role": "assistant", "content": "假设仍无法确认。"},
                "hypotheses": [
                    {
                        "statement": "收入偏低可能与经营日偏少相关",
                        "status": "unresolved",
                        "evidence_references": [],
                    }
                ],
                "signal": "end",
            },
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=MetricEvidenceCollector(),
        scope_resolver=PassthroughScopeResolver(),
    )

    await service.run(
        _runtime_context(),
        ConversationState(),
        [ModelMessage(role="user", content="调查 2026 年 7 月收入为何偏低。")],
    )

    hypothesis = model.calls[1].items[1].hypotheses[0]
    assert hypothesis.statement == "收入偏低可能与经营日偏少相关"
    assert hypothesis.status == "testing"


async def test_native_investigation_returns_unknown_hypothesis_evidence_for_correction() -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "这个假设已经得到支持。"},
                "hypotheses": [
                    {
                        "statement": "收入偏低与经营日偏少相关",
                        "status": "supported",
                        "evidence_references": ["ev_000000000000000000000000"],
                    }
                ],
                "signal": "end",
            },
            {
                "message": {"role": "assistant", "content": "该假设目前仍无法确认。"},
                "hypotheses": [
                    {
                        "statement": "收入偏低与经营日偏少相关",
                        "status": "unresolved",
                        "evidence_references": [],
                    }
                ],
                "signal": "end",
            },
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=MetricEvidenceCollector(),
        scope_resolver=PassthroughScopeResolver(),
    )

    result = await service.run(
        _runtime_context(),
        ConversationState(),
        [ModelMessage(role="user", content="调查 2026 年 7 月收入为何偏低。")],
    )

    correction = model.calls[1].items[-1].message
    assert correction is not None
    assert correction.role == "system"
    assert "未知证据引用" in correction.content
    assert result.turn.content == "该假设目前仍无法确认。"


class FailedEvidenceHypothesisModel:
    def __init__(self) -> None:
        self.calls: list[list[NativeTranscriptItem]] = []

    async def next_turn(self, items, *, tools):
        del tools
        self.calls.append(list(items))
        if len(self.calls) == 1:
            return NativeModelTurn(
                message={"role": "assistant", "content": "先查询。"},
                tool_calls=[
                    NativeToolCall(
                        id="failed",
                        name="monthly_total_revenue",
                        arguments={"year": 2026, "month": 7},
                    )
                ],
                signal="continue",
            )
        if len(self.calls) == 2:
            failed_result = next(item.tool_result for item in items if item.tool_result is not None)
            return NativeModelTurn(
                message={"role": "assistant", "content": "失败结果支持该假设。"},
                hypotheses=[
                    {
                        "statement": "收入偏低与经营日偏少相关",
                        "status": "supported",
                        "evidence_references": [failed_result.evidence.reference],
                    }
                ],
                signal="end",
            )
        return NativeModelTurn(
            message={"role": "assistant", "content": "查询失败，假设仍无法确认。"},
            hypotheses=[
                {
                    "statement": "收入偏低与经营日偏少相关",
                    "status": "unresolved",
                    "evidence_references": [],
                }
            ],
            signal="end",
        )


async def test_native_investigation_does_not_let_failed_evidence_support_a_hypothesis() -> None:
    model = FailedEvidenceHypothesisModel()
    service = NativeToolAgentService(
        model=model,
        evidence_collector=FailingEvidenceCollector(),
        scope_resolver=PassthroughScopeResolver(),
    )

    result = await service.run(
        _runtime_context(),
        ConversationState(),
        [ModelMessage(role="user", content="调查 2026 年 7 月收入为何偏低。")],
    )

    correction = model.calls[2][-1].message
    assert correction is not None
    assert "成功证据" in correction.content
    assert result.turn.content == "查询失败，假设仍无法确认。"


async def test_native_investigation_stops_safely_at_the_round_limit() -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": f"继续第 {round_number} 轮。"},
                "tool_calls": [
                    {
                        "id": f"round-{round_number}",
                        "name": "daily_ledger_revenue",
                        "arguments": {"year": 2026, "month": 7},
                    }
                ],
                "signal": "continue",
            }
            for round_number in range(1, 5)
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=MetricEvidenceCollector(),
        scope_resolver=PassthroughScopeResolver(),
    )

    result = await service.run(
        _runtime_context(),
        ConversationState(),
        [ModelMessage(role="user", content="深入调查 2026 年 7 月。")],
    )

    assert result.turn.route == "answer"
    assert result.turn.content == "调查已达到本轮资源上限；以下结论仅基于已返回的证据。"
    assert len(model.calls) == 4


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
        ("monthly_total_revenue", {"year": 2201, "month": 7}),
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

    assert [tool.name for tool in model.calls[0].tools] == [
        "monthly_total_revenue",
        "daily_ledger_revenue",
        "confirmed_settlement_income",
        "operating_days",
    ]


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
