from datetime import date
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class ModelMessage(ClosedModel):
    role: MessageRole
    content: str = Field(min_length=1, max_length=20_000)


class EvidenceRequestKind(StrEnum):
    BUSINESS_METRICS = "business_metrics"


class EvidenceMetric(StrEnum):
    MONTHLY_TOTAL_REVENUE = "monthly_total_revenue"


MONTHLY_TOTAL_REVENUE_LABEL = "月度总收入"


class CurrentMonthPeriod(ClosedModel):
    kind: Literal["current_month"] = "current_month"


class CalendarMonthPeriod(ClosedModel):
    kind: Literal["calendar_month"]
    year: int = Field(ge=2000, le=2200)
    month: int = Field(ge=1, le=12)


EvidencePeriod = Annotated[
    CurrentMonthPeriod | CalendarMonthPeriod,
    Field(discriminator="kind"),
]


class EvidenceRequest(ClosedModel):
    kind: EvidenceRequestKind
    metric: EvidenceMetric
    period: EvidencePeriod | None = None


class EvidencePlan(ClosedModel):
    requests: list[EvidenceRequest] = Field(min_length=1, max_length=1)


class TurnRoute(StrEnum):
    CLARIFY = "clarify"
    DIRECT_ANSWER = "direct_answer"
    EVIDENCE = "evidence"
    SAFE_FAILURE = "safe_failure"


class TurnPlan(ClosedModel):
    route: TurnRoute
    question: str | None = Field(default=None, min_length=1, max_length=2_000)
    answer: str | None = Field(default=None, min_length=1, max_length=10_000)
    evidence_plan: EvidencePlan | None = None
    message: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def require_only_the_route_payload(self) -> "TurnPlan":
        expected = {
            TurnRoute.CLARIFY: "question",
            TurnRoute.DIRECT_ANSWER: "answer",
            TurnRoute.EVIDENCE: "evidence_plan",
            TurnRoute.SAFE_FAILURE: "message",
        }[self.route]
        payloads = {
            "question": self.question,
            "answer": self.answer,
            "evidence_plan": self.evidence_plan,
            "message": self.message,
        }
        if payloads[expected] is None or any(
            value is not None for name, value in payloads.items() if name != expected
        ):
            raise ValueError(f"{self.route.value} requires only {expected}")
        return self


class EvidencePeriodResult(ClosedModel):
    start: date
    end: date


class MonthlyTotalRevenueResult(ClosedModel):
    daily_ledger_revenue: int = Field(ge=0)
    confirmed_settlement_income: int = Field(ge=0)
    monthly_total_revenue: int = Field(ge=0)


class EvidenceCoverage(ClosedModel):
    calendar_dates: int = Field(ge=1)
    recorded_dates: int = Field(ge=0)


class CurrentStoreScope(ClosedModel):
    id: int = Field(gt=0)


class EvidenceBundle(ClosedModel):
    status: Literal["ok"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    metric: EvidenceMetric
    unit: Literal["EUR"]
    calculation_version: Literal["monthly_total_revenue.v1"]
    result: MonthlyTotalRevenueResult
    coverage: EvidenceCoverage
    comparison: None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool = False
    summary: str = Field(min_length=1, max_length=20_000)


class TurnResult(ClosedModel):
    route: Literal["clarify", "answer", "safe_failure"]
    content: str = Field(min_length=1, max_length=20_000)


class WorkflowResult(ClosedModel):
    turn: TurnResult
    evidence: EvidenceBundle | None = None
