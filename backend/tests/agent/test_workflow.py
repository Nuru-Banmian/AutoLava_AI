from typing import Any

import pytest

from app.agent.contracts import EvidenceBundle, ModelMessage
from app.agent.model import (
    FakeModelAdapter,
    ModelAdapterError,
    ModelErrorCategory,
    ResilientModelAdapter,
)
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags
from app.agent.workflow import AgentTurnWorkflow


class RecordingEvidenceCollector:
    def __init__(self) -> None:
        self.calls = 0

    async def collect(
        self,
        plan: Any,
        context: RuntimeContext,
    ) -> EvidenceBundle:
        del plan
        self.calls += 1
        return EvidenceBundle(
            status="ok",
            current_store={"id": context.store_id},
            period={"start": "2026-07-01", "end": "2026-07-26"},
            metric="monthly_total_revenue",
            unit="EUR",
            calculation_version="monthly_total_revenue.v1",
            result={
                "daily_ledger_revenue": 100,
                "confirmed_settlement_income": 0,
                "monthly_total_revenue": 100,
            },
            coverage={"calendar_dates": 26, "recorded_dates": 1},
            warnings=[],
            summary="本月月度总收入为 100 欧元。",
        )


CONTEXT = RuntimeContext(
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
)


async def test_workflow_finishes_clarification_without_collecting_evidence() -> None:
    model = FakeModelAdapter(plans=[{"route": "clarify", "question": "请说明准确日期。"}])
    collector = RecordingEvidenceCollector()

    result = await AgentTurnWorkflow(model=model, evidence_collector=collector).run(
        [ModelMessage(role="user", content="最近收入如何？")],
        CONTEXT,
    )

    assert result.turn.route == "clarify"
    assert result.turn.content == "请说明准确日期。"
    assert collector.calls == 0
    assert model.total_calls == 1


async def test_workflow_collects_once_then_generates_one_complete_answer() -> None:
    model = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {
                            "kind": "business_metrics",
                            "metric": "monthly_total_revenue",
                        }
                    ]
                },
            }
        ],
        answers=["本月月度总收入为 100 欧元。"],
    )
    collector = RecordingEvidenceCollector()

    result = await AgentTurnWorkflow(model=model, evidence_collector=collector).run(
        [ModelMessage(role="user", content="本月收入是多少？")],
        CONTEXT,
    )

    assert result.turn.route == "answer"
    assert result.turn.content == "本月月度总收入为 100 欧元。"
    assert result.evidence is not None
    assert collector.calls == 1
    assert model.plan_calls == 1
    assert model.answer_calls == 1
    assert model.total_calls == 2


async def test_workflow_converts_model_failure_to_a_sanitized_safe_failure() -> None:
    model = FakeModelAdapter(plans=[ModelAdapterError("api-key=real-secret")])

    result = await AgentTurnWorkflow(
        model=model,
        evidence_collector=RecordingEvidenceCollector(),
    ).run([ModelMessage(role="user", content="本月收入是多少？")], CONTEXT)

    assert result.turn.route == "safe_failure"
    assert result.turn.content == "模型服务暂时不可用，请稍后重试。"
    assert "real-secret" not in result.turn.content


async def test_workflow_repairs_one_structurally_invalid_plan_then_collects() -> None:
    model = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {"requests": [{"kind": "business_metrics"}]},
            },
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {
                            "kind": "business_metrics",
                            "metric": "monthly_total_revenue",
                        }
                    ]
                },
            },
        ],
        answers=["本月月度总收入为 100 欧元。"],
    )
    collector = RecordingEvidenceCollector()

    result = await AgentTurnWorkflow(model=model, evidence_collector=collector).run(
        [ModelMessage(role="user", content="本月收入是多少？")],
        CONTEXT,
    )

    assert result.turn.route == "answer"
    assert model.plan_calls == 2
    assert model.answer_calls == 1
    assert collector.calls == 1


async def test_workflow_does_not_retry_a_plan_that_claims_store_scope() -> None:
    model = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {
                            "kind": "business_metrics",
                            "metric": "monthly_total_revenue",
                            "store_id": 999,
                        }
                    ]
                },
            },
            {"route": "direct_answer", "answer": "不应使用备用计划。"},
        ]
    )
    collector = RecordingEvidenceCollector()

    result = await AgentTurnWorkflow(model=model, evidence_collector=collector).run(
        [ModelMessage(role="user", content="查询另一个门店")],
        CONTEXT,
    )

    assert result.turn.route == "safe_failure"
    assert model.plan_calls == 1
    assert collector.calls == 0


async def test_workflow_replaces_unsupported_amounts_and_raw_json_with_safe_summary() -> None:
    evidence_plan = {
        "route": "evidence",
        "evidence_plan": {
            "requests": [
                {
                    "kind": "business_metrics",
                    "metric": "monthly_total_revenue",
                }
            ]
        },
    }
    for unsafe_answer in (
        "2026-07-01 至 2026-07-26 的月度总收入为 999 欧元。",
        (
            "2026-07-01 至 2026-07-26 的月度总收入为 100 欧元，"
            "其中每日台账营业额 0 欧元，已确认公司结算收入 100 欧元。"
        ),
        '{"status":"ok","monthly_total_revenue":100}',
    ):
        result = await AgentTurnWorkflow(
            model=FakeModelAdapter(
                plans=[evidence_plan],
                answers=[unsafe_answer],
            ),
            evidence_collector=RecordingEvidenceCollector(),
        ).run(
            [ModelMessage(role="user", content="本月收入是多少？")],
            CONTEXT,
        )

        assert result.turn.content == "本月月度总收入为 100 欧元。"


@pytest.mark.parametrize(
    "category",
    (
        ModelErrorCategory.TIMEOUT,
        ModelErrorCategory.RATE_LIMIT,
        ModelErrorCategory.PROVIDER_5XX,
        ModelErrorCategory.NETWORK,
    ),
)
async def test_transient_failure_retries_current_model_once(
    category: ModelErrorCategory,
) -> None:
    primary = FakeModelAdapter(
        plans=[
            ModelAdapterError("provider detail", category=category),
            {"route": "direct_answer", "answer": "恢复后的回答"},
        ],
        provider="primary",
    )

    result = await AgentTurnWorkflow(
        model=ResilientModelAdapter(primary),
        evidence_collector=RecordingEvidenceCollector(),
    ).run([ModelMessage(role="user", content="问题")], CONTEXT)

    assert result.turn.content == "恢复后的回答"
    assert result.turn.recovery_status == "retried"
    assert primary.plan_calls == 2


async def test_fallback_redoes_only_answer_stage_with_same_evidence() -> None:
    primary = FakeModelAdapter(
        plans=[
            {
                "route": "evidence",
                "evidence_plan": {
                    "requests": [
                        {
                            "kind": "business_metrics",
                            "metric": "monthly_total_revenue",
                        }
                    ]
                },
            }
        ],
        answers=[
            ModelAdapterError("timeout", category=ModelErrorCategory.TIMEOUT),
            ModelAdapterError("still down", category=ModelErrorCategory.PROVIDER_5XX),
        ],
        provider="primary",
    )
    fallback = FakeModelAdapter(
        answers=["本月月度总收入为 100 欧元。"],
        provider="fallback",
    )
    collector = RecordingEvidenceCollector()

    result = await AgentTurnWorkflow(
        model=ResilientModelAdapter(primary, fallback=fallback),
        evidence_collector=collector,
    ).run([ModelMessage(role="user", content="本月收入是多少？")], CONTEXT)

    assert result.turn.content == "本月月度总收入为 100 欧元。"
    assert result.turn.recovery_status == "fallback"
    assert collector.calls == 1
    assert primary.plan_calls == 1
    assert primary.answer_calls == 2
    assert fallback.plan_calls == 0
    assert fallback.answer_calls == 1


@pytest.mark.parametrize(
    "category",
    (
        ModelErrorCategory.INVALID_API_KEY,
        ModelErrorCategory.INSUFFICIENT_BALANCE,
        ModelErrorCategory.INVALID_REQUEST,
        ModelErrorCategory.SAFETY_REFUSAL,
        ModelErrorCategory.PERMISSION_DENIED,
        ModelErrorCategory.INSUFFICIENT_USER_INFO,
        ModelErrorCategory.PROMPT_INJECTION,
    ),
)
async def test_non_recoverable_failure_never_retries_or_uses_fallback(
    category: ModelErrorCategory,
) -> None:
    primary = FakeModelAdapter(
        plans=[ModelAdapterError("secret provider detail", category=category)]
    )
    fallback = FakeModelAdapter(
        plans=[{"route": "direct_answer", "answer": "不应绕过"}]
    )

    result = await AgentTurnWorkflow(
        model=ResilientModelAdapter(primary, fallback=fallback),
        evidence_collector=RecordingEvidenceCollector(),
    ).run([ModelMessage(role="user", content="问题")], CONTEXT)

    assert result.turn.route == "safe_failure"
    assert "secret provider detail" not in result.turn.content
    assert primary.plan_calls == 1
    assert fallback.plan_calls == 0


async def test_all_providers_unavailable_returns_sanitized_failure() -> None:
    def unavailable(message: str) -> ModelAdapterError:
        return ModelAdapterError(
            message, category=ModelErrorCategory.PROVIDER_5XX
        )
    primary = FakeModelAdapter(
        plans=[unavailable("primary raw"), unavailable("primary raw again")]
    )
    fallback = FakeModelAdapter(plans=[unavailable("fallback raw")])

    result = await AgentTurnWorkflow(
        model=ResilientModelAdapter(primary, fallback=fallback),
        evidence_collector=RecordingEvidenceCollector(),
    ).run([ModelMessage(role="user", content="问题")], CONTEXT)

    assert result.turn.route == "safe_failure"
    assert result.turn.recovery_status == "fallback"
    assert "raw" not in result.turn.content
