from __future__ import annotations

from datetime import date as CalendarDate
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)


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
    WASH_COUNT = "wash_count"
    AVERAGE_REVENUE_PER_CAR = "average_revenue_per_car"
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
    EvidenceMetric.WASH_COUNT: "洗车数量",
    EvidenceMetric.AVERAGE_REVENUE_PER_CAR: "平均每车收入",
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


class EvidenceGroup(StrEnum):
    DATE = "date"
    CALENDAR_MONTH = "calendar_month"
    CALENDAR_YEAR = "calendar_year"
    INCOME_CATEGORY = "income_category"
    RECORDED_WEATHER = "recorded_weather"
    WEEKDAY = "weekday"
    OPERATING_STATUS = "operating_status"


class EvidenceWeekday(StrEnum):
    MONDAY = "星期一"
    TUESDAY = "星期二"
    WEDNESDAY = "星期三"
    THURSDAY = "星期四"
    FRIDAY = "星期五"
    SATURDAY = "星期六"
    SUNDAY = "星期日"


FilterText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=100),
]
WeatherFilterText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=50),
]


class EvidenceFilters(ClosedModel):
    income_categories: list[FilterText] = Field(default_factory=list, max_length=10)
    recorded_weather: list[WeatherFilterText] = Field(default_factory=list, max_length=10)
    weekdays: list[EvidenceWeekday] = Field(default_factory=list, max_length=7)
    operating_statuses: list[Literal["营业", "休息", "提前休息"]] = Field(
        default_factory=list,
        max_length=3,
    )

    @field_validator(
        "income_categories",
        "recorded_weather",
        "weekdays",
        "operating_statuses",
    )
    @classmethod
    def require_unique_filter_values(cls, values: list[object]) -> list[object]:
        normalized = [
            value.casefold() if isinstance(value, str) else str(value).casefold()
            for value in values
        ]
        if len(normalized) != len(set(normalized)):
            raise ValueError("filter values must be unique")
        return values

    @model_validator(mode="after")
    def bound_total_filter_values(self) -> "EvidenceFilters":
        total = (
            len(self.income_categories)
            + len(self.recorded_weather)
            + len(self.weekdays)
            + len(self.operating_statuses)
        )
        if total > 20:
            raise ValueError("at most 20 filter values are allowed")
        return self


class EvidenceRequest(ClosedModel):
    kind: Literal["business_metrics"] = "business_metrics"
    metric: EvidenceMetric
    period: EvidencePeriod | None = None
    group_by: EvidenceGroup | None = None
    filters: EvidenceFilters | None = None
    extreme: Literal["highest", "lowest"] | None = None
    comparison: EvidenceComparisonRequest | None = None

    @model_validator(mode="after")
    def require_compatible_query_shape(self) -> "EvidenceRequest":
        if self.metric == EvidenceMetric.DAILY_LEDGER:
            raise ValueError("daily ledger requires the daily_ledger request kind")
        if (
            self.comparison is not None
            and self.metric != EvidenceMetric.MONTHLY_TOTAL_REVENUE
        ):
            raise ValueError("period comparison requires monthly total revenue")
        if self.comparison is not None and (
            self.group_by is not None or self.filters is not None or self.extreme is not None
        ):
            raise ValueError("period comparison cannot be combined with grouping or filtering")
        if self.extreme is not None and self.metric != EvidenceMetric.DAILY_LEDGER_REVENUE:
            raise ValueError("daily extremes require daily ledger revenue")
        if self.extreme is not None and self.group_by is not None:
            raise ValueError("daily extremes cannot also be grouped")
        if self.group_by is not None:
            daily_metrics = {
                EvidenceMetric.DAILY_LEDGER_REVENUE,
                EvidenceMetric.OPERATING_DAYS,
                EvidenceMetric.OPERATING_DAY_AVERAGE_LEDGER_REVENUE,
                EvidenceMetric.INCOME_CATEGORY_AMOUNT,
                EvidenceMetric.OTHER_DATA_AMOUNT,
            }
            if self.metric not in daily_metrics:
                raise ValueError("this metric has no safe daily grouping grain")
            if (
                self.group_by == EvidenceGroup.INCOME_CATEGORY
                and self.metric
                not in {
                    EvidenceMetric.DAILY_LEDGER_REVENUE,
                    EvidenceMetric.INCOME_CATEGORY_AMOUNT,
                    EvidenceMetric.OTHER_DATA_AMOUNT,
                }
            ):
                raise ValueError("income category grouping requires an amount metric")
        if self.filters is not None and self.metric in {
            EvidenceMetric.MONTHLY_TOTAL_REVENUE,
            EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME,
            EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME,
        }:
            raise ValueError("this metric cannot be safely filtered at daily grain")
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


class EvidenceGroupRow(ClosedModel):
    key: str = Field(min_length=1, max_length=160)
    label: str = Field(min_length=1, max_length=160)
    value: int | None = Field(default=None, ge=0)


class GroupedMetricResult(ClosedModel):
    group_by: EvidenceGroup
    rows: list[EvidenceGroupRow] = Field(max_length=400)


class DailyLedgerExtremeResult(ClosedModel):
    extreme: Literal["highest", "lowest"]
    daily_ledger_revenue: int | None = Field(default=None, ge=0)
    dates: list[CalendarDate]


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
    | WashCountResult
    | AverageRevenuePerCarResult
    | CategoryAmountResult
    | GroupedMetricResult
    | DailyLedgerExtremeResult
    | DailyLedgerResult
)


class EvidenceCoverage(ClosedModel):
    calendar_dates: int = Field(ge=1)
    recorded_dates: int = Field(ge=0)


class CategoryTotalMismatch(ClosedModel):
    date: CalendarDate
    daily_ledger_revenue: int = Field(ge=0)
    included_category_amount: int = Field(ge=0)


class EvidenceCompleteness(ClosedModel):
    status: Literal["sufficient", "limited"]
    unrecorded_dates: list[CalendarDate] = Field(default_factory=list)
    missing_weather_dates: list[CalendarDate] = Field(default_factory=list)
    wash_count_enabled: bool
    operating_days: int = Field(ge=0)
    wash_count_recorded_operating_days: int = Field(ge=0)
    wash_count_missing_dates: list[CalendarDate] = Field(default_factory=list)
    wash_count_coverage_percent: int | None = Field(default=None, ge=0, le=100)
    wash_count_sufficient: bool
    category_total_mismatches: list[CategoryTotalMismatch] = Field(default_factory=list)


class CurrentStoreScope(ClosedModel):
    id: int = Field(gt=0)


class EvidenceBundle(ClosedModel):
    status: Literal["ok", "not_recorded"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    metric: EvidenceMetric
    group_by: EvidenceGroup | None = None
    filters: EvidenceFilters | None = None
    extreme: Literal["highest", "lowest"] | None = None
    unit: Literal[
        "EUR",
        "day",
        "car",
        "EUR/car",
        "EUR/operating_day",
        "mixed",
    ]
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
        "grouped_business_metric.v1",
        "daily_ledger_extreme.v1",
        "daily_ledger.v1",
    ]
    result: EvidenceResult
    coverage: EvidenceCoverage
    completeness: EvidenceCompleteness | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
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
            or self.group_by is not None
            or self.filters is not None
            or self.extreme is not None
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
