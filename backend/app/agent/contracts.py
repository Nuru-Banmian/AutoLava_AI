from __future__ import annotations

from datetime import date as CalendarDate
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
    DAILY_LEDGER = "daily_ledger"


class EvidenceMetric(StrEnum):
    MONTHLY_TOTAL_REVENUE = "monthly_total_revenue"
    DAILY_LEDGER = "daily_ledger"


MONTHLY_TOTAL_REVENUE_LABEL = "月度总收入"
DAILY_LEDGER_LABEL = "每日台账"


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
    metric: EvidenceMetric | None = None
    period: EvidencePeriod | None = None
    date: CalendarDate | None = None

    @model_validator(mode="after")
    def require_only_the_request_payload(self) -> "EvidenceRequest":
        if self.kind == EvidenceRequestKind.BUSINESS_METRICS:
            if (
                self.metric is None
                or self.metric == EvidenceMetric.DAILY_LEDGER
                or self.date is not None
            ):
                raise ValueError("business_metrics requires metric and forbids date")
            return self
        if self.metric is not None or self.period is not None or self.date is None:
            raise ValueError("daily_ledger requires only an exact date")
        return self


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
    start: CalendarDate
    end: CalendarDate


class MonthlyTotalRevenueResult(ClosedModel):
    daily_ledger_revenue: int = Field(ge=0)
    confirmed_settlement_income: int = Field(ge=0)
    monthly_total_revenue: int = Field(ge=0)


class DailyLedgerAmount(ClosedModel):
    name: str = Field(min_length=1, max_length=100)
    amount: int = Field(ge=0)


class DailyLedgerFacts(ClosedModel):
    date: CalendarDate
    daily_revenue: int = Field(ge=0)
    income_mode: Literal["总额记账", "分类记账"]
    income_categories: list[DailyLedgerAmount] = Field(default_factory=list)
    other_data: list[DailyLedgerAmount] = Field(default_factory=list)
    operating_status: Literal["营业", "休息", "提前休息"]
    recorded_weather: str | None = Field(default=None, max_length=50)
    wash_count: int | None = Field(default=None, ge=0)


class UntrustedRawEvent(ClosedModel):
    text: str = Field(min_length=1, max_length=2_000)
    trust: Literal["untrusted_business_data"] = "untrusted_business_data"


class DailyLedgerResult(ClosedModel):
    facts: DailyLedgerFacts | None
    missing_fields: list[Literal["recorded_weather", "wash_count"]] = Field(
        default_factory=list
    )
    unavailable_fields: list[Literal["wash_count"]] = Field(default_factory=list)
    raw_event: UntrustedRawEvent | None = None


class EvidenceCoverage(ClosedModel):
    calendar_dates: int = Field(ge=1)
    recorded_dates: int = Field(ge=0)


class CurrentStoreScope(ClosedModel):
    id: int = Field(gt=0)


class EvidenceBundle(ClosedModel):
    status: Literal["ok", "not_recorded"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    metric: EvidenceMetric
    unit: Literal["EUR", "mixed"]
    calculation_version: Literal[
        "monthly_total_revenue.v1", "daily_ledger.v1"
    ]
    result: MonthlyTotalRevenueResult | DailyLedgerResult
    coverage: EvidenceCoverage
    comparison: None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool = False
    summary: str = Field(min_length=1, max_length=20_000)

    @model_validator(mode="after")
    def require_consistent_evidence_shape(self) -> "EvidenceBundle":
        if self.metric == EvidenceMetric.MONTHLY_TOTAL_REVENUE:
            if (
                self.status != "ok"
                or self.unit != "EUR"
                or self.calculation_version != "monthly_total_revenue.v1"
                or not isinstance(self.result, MonthlyTotalRevenueResult)
            ):
                raise ValueError("monthly revenue evidence has an inconsistent shape")
            return self
        if (
            self.unit != "mixed"
            or self.calculation_version != "daily_ledger.v1"
            or not isinstance(self.result, DailyLedgerResult)
            or self.period.start != self.period.end
            or self.coverage.calendar_dates != 1
        ):
            raise ValueError("daily ledger evidence has an inconsistent shape")
        if self.status == "not_recorded":
            if self.result.facts is not None or self.coverage.recorded_dates != 0:
                raise ValueError("not-recorded daily ledger cannot contain facts")
        elif (
            self.result.facts is None
            or self.result.facts.date != self.period.start
            or self.coverage.recorded_dates != 1
        ):
            raise ValueError("recorded daily ledger requires facts")
        return self


class TurnResult(ClosedModel):
    route: Literal["clarify", "answer", "safe_failure"]
    content: str = Field(min_length=1, max_length=20_000)


class WorkflowResult(ClosedModel):
    turn: TurnResult
    evidence: EvidenceBundle | None = None
