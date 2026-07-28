from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select

from app.agent.contracts import TurnResult
from app.agent.model import (
    CONFIGURATION_CATEGORIES,
    RECOVERABLE_CATEGORIES,
    ModelAttempt,
    ModelErrorCategory,
)
from app.models.agent import AgentAlert, AgentRunStat

BUDGET_WARNING_RATIO = 0.8


@dataclass(frozen=True)
class AlertDescriptor:
    alert_type: str
    provider: str
    model: str
    error_category: str
    message: str


def _utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


def _failure_alert(
    attempt: ModelAttempt,
    *,
    unrecovered: bool,
) -> AlertDescriptor | None:
    category = attempt.error_category
    if category is None:
        return None
    if category in CONFIGURATION_CATEGORIES:
        if category is ModelErrorCategory.INSUFFICIENT_BALANCE:
            alert_type = "budget"
            message = "模型预算不可用，请检查供应商账户。"
        else:
            alert_type = "configuration"
            message = "模型配置不可用，请检查供应商设置。"
        return AlertDescriptor(
            alert_type=alert_type,
            provider=attempt.provider,
            model=attempt.model,
            error_category=category.value,
            message=message,
        )
    if unrecovered and category in RECOVERABLE_CATEGORIES:
        return AlertDescriptor(
            alert_type="service",
            provider=attempt.provider,
            model=attempt.model,
            error_category=category.value,
            message="模型服务持续不可用，请检查供应商状态。",
        )
    return None


async def _record_alert(
    session,
    *,
    descriptor: AlertDescriptor,
    now: datetime,
) -> None:
    alert = await session.scalar(
        select(AgentAlert)
        .where(
            AgentAlert.alert_type == descriptor.alert_type,
            AgentAlert.provider == descriptor.provider,
            AgentAlert.model == descriptor.model,
            AgentAlert.error_category == descriptor.error_category,
        )
        .order_by(AgentAlert.id.desc())
        .limit(1)
    )
    if alert is None:
        session.add(
            AgentAlert(
                alert_type=descriptor.alert_type,
                provider=descriptor.provider,
                model=descriptor.model,
                error_category=descriptor.error_category,
                message=descriptor.message,
                occurrence_count=1,
                is_resolved=False,
                last_seen_at=now,
            )
        )
        return
    alert.message = descriptor.message
    alert.occurrence_count += 1
    alert.last_seen_at = now
    alert.is_resolved = False
    alert.resolved_at = None


async def record_agent_observability(
    session,
    *,
    run_id: str,
    user_id: int,
    store_id: int,
    role: str,
    attempts: Iterable[ModelAttempt],
    turn: TurnResult,
    max_cost_eur: float,
) -> None:
    attempt_list = list(attempts)
    now = _utc_now()
    for attempt in attempt_list:
        session.add(
            AgentRunStat(
                run_id=run_id,
                user_id=user_id,
                store_id=store_id,
                role=role,
                stage=attempt.stage,
                provider=attempt.provider,
                model=attempt.model,
                input_tokens=attempt.input_tokens,
                output_tokens=attempt.output_tokens,
                result=attempt.result,
                error_category=(
                    attempt.error_category.value if attempt.error_category is not None else None
                ),
                latency_ms=attempt.latency_ms,
                estimated_cost=attempt.estimated_cost,
                is_fallback=attempt.is_fallback,
            )
        )

    alert_descriptors: dict[AlertDescriptor, None] = {}
    unrecovered = turn.route == "safe_failure"
    for attempt in attempt_list:
        descriptor = _failure_alert(attempt, unrecovered=unrecovered)
        if descriptor is None:
            continue
        alert_descriptors.setdefault(descriptor, None)

    known_cost = sum(
        attempt.estimated_cost for attempt in attempt_list if attempt.estimated_cost is not None
    )
    if attempt_list and known_cost >= max_cost_eur * BUDGET_WARNING_RATIO:
        last_attempt = attempt_list[-1]
        alert_descriptors.setdefault(
            AlertDescriptor(
                alert_type="budget",
                provider=last_attempt.provider,
                model=last_attempt.model,
                error_category="budget_near_limit",
                message="本次模型费用接近调查预算上限，请检查预算设置。",
            ),
            None,
        )

    for descriptor in alert_descriptors:
        await _record_alert(
            session,
            descriptor=descriptor,
            now=now,
        )
