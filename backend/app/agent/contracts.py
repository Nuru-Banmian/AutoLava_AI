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
    DAILY_LEDGER_REVENUE = "daily_ledger_revenue"
    CONFIRMED_SETTLEMENT_INCOME = "confirmed_settlement_income"
    OPERATING_DAYS = "operating_days"
    OPERATING_DAY_AVERAGE_LEDGER_REVENUE = "operating_day_average_ledger_revenue"
    MONTHLY_DAILY_AVERAGE_INCOME = "monthly_daily_average_income"
    WASH_COUNT = "wash_count"
    AVERAGE_REVENUE_PER_CAR = "average_revenue_per_car"
    INCOME_CATEGORY_AMOUNT = "income_category_amount"
    OTHER_DATA_AMOUNT = "other_data_amount"


EVIDENCE_METRIC_LABELS = {
    EvidenceMetric.MONTHLY_TOTAL_REVENUE: "月度总收入",
    EvidenceMetric.DAILY_LEDGER_REVENUE: "每日台账营业额",
    EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME: "已确认公司结算收入",
    EvidenceMetric.OPERATING_DAYS: "经营日",
    EvidenceMetric.OPERATING_DAY_AVERAGE_LEDGER_REVENUE: "经营日均台账营业额",
    EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME: "月度日均收入",
    EvidenceMetric.WASH_COUNT: "洗车数量",
    EvidenceMetric.AVERAGE_REVENUE_PER_CAR: "平均每车收入",
    EvidenceMetric.INCOME_CATEGORY_AMOUNT: "收入分类金额",
    EvidenceMetric.OTHER_DATA_AMOUNT: "其他数据金额",
}


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
    group_by: Literal["income_category"] | None = None

    @model_validator(mode="after")
    def require_category_group_only_for_category_metrics(self) -> "EvidenceRequest":
        if self.group_by is not None and self.metric not in {
            EvidenceMetric.INCOME_CATEGORY_AMOUNT,
            EvidenceMetric.OTHER_DATA_AMOUNT,
        }:
            raise ValueError("income category grouping requires a category metric")
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
    start: date
    end: date


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


class WashCountResult(ClosedModel):
    available: bool
    wash_count: int | None = Field(default=None, ge=0)


class AverageRevenuePerCarResult(ClosedModel):
    available: bool
    daily_ledger_revenue: int | None = Field(default=None, ge=0)
    wash_count: int | None = Field(default=None, ge=0)
    average_revenue_per_car: int | None = Field(default=None, ge=0)


class CategoryAmountRow(ClosedModel):
    category_id: int = Field(gt=0)
    category_name: str = Field(min_length=1, max_length=100)
    include_in_total: bool
    sort_order: int
    amount: int = Field(ge=0)


class CategoryAmountResult(ClosedModel):
    amount: int = Field(ge=0)
    categories: list[CategoryAmountRow]


EvidenceResult = (
    MonthlyTotalRevenueResult
    | DailyLedgerRevenueResult
    | ConfirmedSettlementIncomeResult
    | OperatingDaysResult
    | OperatingDayAverageLedgerRevenueResult
    | MonthlyDailyAverageIncomeResult
    | WashCountResult
    | AverageRevenuePerCarResult
    | CategoryAmountResult
)


class EvidenceCoverage(ClosedModel):
    calendar_dates: int = Field(ge=1)
    recorded_dates: int = Field(ge=0)
    operating_days: int = Field(default=0, ge=0)
    weather_recorded_dates: int = Field(default=0, ge=0)
    wash_count_enabled: bool = True
    wash_count_recorded_operating_days: int = Field(default=0, ge=0)
    wash_count_missing_operating_days: int = Field(default=0, ge=0)
    wash_count_coverage_percent: int | None = Field(default=None, ge=0, le=100)
    wash_count_sufficient: bool = False


class CategoryTotalMismatch(ClosedModel):
    date: date
    daily_ledger_revenue: int = Field(ge=0)
    included_category_amount: int = Field(ge=0)


class EvidenceCompleteness(ClosedModel):
    status: Literal["sufficient", "limited"] = "sufficient"
    unrecorded_dates: list[date] = Field(default_factory=list)
    missing_weather_dates: list[date] = Field(default_factory=list)
    wash_count_missing_dates: list[date] = Field(default_factory=list)
    category_total_mismatches: list[CategoryTotalMismatch] = Field(default_factory=list)


class CurrentStoreScope(ClosedModel):
    id: int = Field(gt=0)


class EvidenceBundle(ClosedModel):
    status: Literal["ok"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    metric: EvidenceMetric
    unit: Literal["EUR", "day", "car", "EUR/car", "EUR/operating_day"]
    calculation_version: Literal[
        "monthly_total_revenue.v1",
        "daily_ledger_revenue.v1",
        "confirmed_settlement_income.v1",
        "operating_days.v1",
        "operating_day_average_ledger_revenue.v1",
        "monthly_daily_average_income.v1",
        "wash_count.v1",
        "average_revenue_per_car.v1",
        "income_category_amount.v1",
        "other_data_amount.v1",
    ]
    result: EvidenceResult
    coverage: EvidenceCoverage
    completeness: EvidenceCompleteness = Field(default_factory=EvidenceCompleteness)
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
