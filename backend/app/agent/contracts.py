from __future__ import annotations

from datetime import date as CalendarDate
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator


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
    SETTLEMENT_DETAILS = "settlement_details"
    DAILY_LEDGER = "daily_ledger"


class EvidenceMetric(StrEnum):
    MONTHLY_TOTAL_REVENUE = "monthly_total_revenue"
    DAILY_LEDGER_REVENUE = "daily_ledger_revenue"
    CONFIRMED_SETTLEMENT_INCOME = "confirmed_settlement_income"
    OPERATING_DAYS = "operating_days"
    OPERATING_DAY_AVERAGE_LEDGER_REVENUE = "operating_day_average_ledger_revenue"
    MONTHLY_DAILY_AVERAGE_INCOME = "monthly_daily_average_income"
    INCOME_CATEGORY_AMOUNT = "income_category_amount"
    OTHER_DATA_AMOUNT = "other_data_amount"
    DAILY_LEDGER = "daily_ledger"


EVIDENCE_METRIC_LABELS = {
    EvidenceMetric.MONTHLY_TOTAL_REVENUE: "月度总收入",
    EvidenceMetric.DAILY_LEDGER_REVENUE: "每日台账营业额",
    EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME: "已确认公司结算收入",
    EvidenceMetric.OPERATING_DAYS: "经营日",
    EvidenceMetric.OPERATING_DAY_AVERAGE_LEDGER_REVENUE: "经营日均台账营业额",
    EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME: "月度日均收入",
    EvidenceMetric.INCOME_CATEGORY_AMOUNT: "收入分类金额",
    EvidenceMetric.OTHER_DATA_AMOUNT: "其他数据金额",
    EvidenceMetric.DAILY_LEDGER: "每日台账",
}
SETTLEMENT_DETAILS_LABEL = "公司结算明细"
MONTHLY_TOTAL_REVENUE_LABEL = "月度总收入"
DAILY_LEDGER_LABEL = "每日台账"
MINIMUM_EVIDENCE_DATE = CalendarDate(2000, 1, 1)
MAXIMUM_EVIDENCE_DATE = CalendarDate(2200, 12, 31)


class CurrentMonthPeriod(ClosedModel):
    kind: Literal["current_month"] = "current_month"


class PreviousMonthPeriod(ClosedModel):
    kind: Literal["previous_month"] = "previous_month"


class PreviousMonthToDatePeriod(ClosedModel):
    kind: Literal["previous_month_to_date"] = "previous_month_to_date"


class CalendarMonthPeriod(ClosedModel):
    kind: Literal["calendar_month"]
    year: int = Field(ge=2000, le=2200)
    month: int = Field(ge=1, le=12)


class CalendarYearPeriod(ClosedModel):
    kind: Literal["calendar_year"]
    year: int = Field(ge=2000, le=2200)


class ExactDatePeriod(ClosedModel):
    kind: Literal["exact_date"]
    on: CalendarDate = Field(
        alias="date",
        ge=MINIMUM_EVIDENCE_DATE,
        le=MAXIMUM_EVIDENCE_DATE,
    )


class CustomDateRangePeriod(ClosedModel):
    kind: Literal["custom_date_range"]
    start: CalendarDate = Field(
        ge=MINIMUM_EVIDENCE_DATE,
        le=MAXIMUM_EVIDENCE_DATE,
    )
    end: CalendarDate = Field(
        ge=MINIMUM_EVIDENCE_DATE,
        le=MAXIMUM_EVIDENCE_DATE,
    )

    @model_validator(mode="after")
    def require_forward_range(self) -> "CustomDateRangePeriod":
        if self.end < self.start:
            raise ValueError("custom date range end must not precede start")
        return self


EvidencePeriod = Annotated[
    CurrentMonthPeriod
    | PreviousMonthPeriod
    | PreviousMonthToDatePeriod
    | CalendarMonthPeriod
    | CalendarYearPeriod
    | ExactDatePeriod
    | CustomDateRangePeriod,
    Field(discriminator="kind"),
]


class EvidenceComparisonRequest(ClosedModel):
    period: EvidencePeriod
    include_percentage: bool = False


class EvidenceRequest(ClosedModel):
    kind: Literal["business_metrics"] = "business_metrics"
    metric: EvidenceMetric
    period: EvidencePeriod | None = None
    group_by: Literal["income_category"] | None = None
    comparison: EvidenceComparisonRequest | None = None

    @model_validator(mode="after")
    def require_category_group_only_for_category_metrics(self) -> "EvidenceRequest":
        if self.metric == EvidenceMetric.DAILY_LEDGER:
            raise ValueError("daily ledger requires the daily_ledger request kind")
        if self.group_by is not None and self.metric not in {
            EvidenceMetric.INCOME_CATEGORY_AMOUNT,
            EvidenceMetric.OTHER_DATA_AMOUNT,
        }:
            raise ValueError("income category grouping requires a category metric")
        if (
            self.comparison is not None
            and self.metric != EvidenceMetric.MONTHLY_TOTAL_REVENUE
        ):
            raise ValueError("period comparison requires monthly total revenue")
        return self


SettlementCompanyName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120),
]


class SettlementDetailsRequest(ClosedModel):
    kind: Literal["settlement_details"] = "settlement_details"
    period: EvidencePeriod | None = None
    status: Literal["pending", "confirmed"] | None = None
    company_name: SettlementCompanyName | None = None


class DailyLedgerRequest(ClosedModel):
    kind: Literal["daily_ledger"] = "daily_ledger"
    date: CalendarDate


EvidenceRequestUnion = Annotated[
    EvidenceRequest | SettlementDetailsRequest | DailyLedgerRequest,
    Field(discriminator="kind"),
]


class EvidencePlan(ClosedModel):
    requests: list[EvidenceRequestUnion] = Field(min_length=1, max_length=1)


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


class DailyLedgerRevenueResult(ClosedModel):
    daily_ledger_revenue: int = Field(ge=0)


class ConfirmedSettlementIncomeResult(ClosedModel):
    confirmed_settlement_income: int = Field(ge=0)


class OperatingDaysResult(ClosedModel):
    operating_days: int = Field(ge=0)


class OperatingDayAverageLedgerRevenueResult(ClosedModel):
    daily_ledger_revenue: int = Field(ge=0)
    operating_days: int = Field(ge=0)
    operating_day_average_ledger_revenue: int | None = Field(default=None, ge=0)


class MonthlyDailyAverageIncomeResult(ClosedModel):
    daily_ledger_revenue: int = Field(ge=0)
    confirmed_settlement_income: int = Field(ge=0)
    monthly_total_revenue: int = Field(ge=0)
    operating_days: int = Field(ge=0)
    monthly_daily_average_income: int | None = Field(default=None, ge=0)


class CategoryAmountRow(ClosedModel):
    category_id: int = Field(gt=0)
    category_name: str = Field(min_length=1, max_length=100)
    include_in_total: bool
    sort_order: int
    amount: int = Field(ge=0)


class CategoryAmountResult(ClosedModel):
    amount: int = Field(ge=0)
    categories: list[CategoryAmountRow]


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


class EvidenceComparisonResult(ClosedModel):
    status: Literal["ok", "no_data"]
    period: EvidencePeriodResult
    result: MonthlyTotalRevenueResult | None
    amount_difference: int | None
    percentage_change: float | None
    percentage_status: Literal[
        "not_requested",
        "available",
        "unavailable_zero_baseline",
        "unavailable_no_data",
    ]
    equal_length: bool


EvidenceResult = (
    MonthlyTotalRevenueResult
    | DailyLedgerRevenueResult
    | ConfirmedSettlementIncomeResult
    | OperatingDaysResult
    | OperatingDayAverageLedgerRevenueResult
    | MonthlyDailyAverageIncomeResult
    | CategoryAmountResult
    | DailyLedgerResult
)


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
    unit: Literal["EUR", "day", "EUR/operating_day", "mixed"]
    calculation_version: Literal[
        "monthly_total_revenue.v1",
        "daily_ledger_revenue.v1",
        "confirmed_settlement_income.v1",
        "operating_days.v1",
        "operating_day_average_ledger_revenue.v1",
        "monthly_daily_average_income.v1",
        "income_category_amount.v1",
        "other_data_amount.v1",
        "daily_ledger.v1",
    ]
    result: EvidenceResult
    coverage: EvidenceCoverage
    comparison: EvidenceComparisonResult | None = None
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
        if self.metric != EvidenceMetric.DAILY_LEDGER:
            if (
                self.status != "ok"
                or self.unit == "mixed"
                or self.calculation_version == "daily_ledger.v1"
                or isinstance(self.result, DailyLedgerResult)
            ):
                raise ValueError("business metric evidence has an inconsistent shape")
            return self
        if (
            self.unit != "mixed"
            or self.calculation_version != "daily_ledger.v1"
            or not isinstance(self.result, DailyLedgerResult)
            or self.comparison is not None
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


class SettlementCompanyEvidence(ClosedModel):
    name: str = Field(min_length=1, max_length=120)
    is_active: bool
    pending_amount: int = Field(ge=0)
    confirmed_amount: int = Field(ge=0)
    record_count: int = Field(ge=0)


class SettlementRecordEvidence(ClosedModel):
    company_name: str = Field(min_length=1, max_length=120)
    opening_month: CalendarDate
    amount: int = Field(gt=0)
    status: Literal["pending", "confirmed"]


class SettlementDetailsResult(ClosedModel):
    companies: list[SettlementCompanyEvidence] = Field(max_length=50)
    records: list[SettlementRecordEvidence] = Field(max_length=50)
    pending_amount: int = Field(ge=0)
    confirmed_amount: int = Field(ge=0)
    pending_records: int = Field(ge=0)
    confirmed_records: int = Field(ge=0)


class SettlementDetailsEvidenceBundle(ClosedModel):
    status: Literal["ok", "refused"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    evidence_type: Literal["settlement_details"] = "settlement_details"
    unit: Literal["EUR"] = "EUR"
    calculation_version: Literal["settlement_details.v1"] = "settlement_details.v1"
    result: SettlementDetailsResult
    warnings: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool = False
    summary: str = Field(min_length=1, max_length=20_000)


CollectedEvidence = EvidenceBundle | SettlementDetailsEvidenceBundle


class TurnResult(ClosedModel):
    route: Literal["clarify", "answer", "safe_failure"]
    content: str = Field(min_length=1, max_length=20_000)
    recovery_status: Literal["none", "retried", "fallback"] = "none"


class WorkflowResult(ClosedModel):
    turn: TurnResult
    evidence: CollectedEvidence | None = None
