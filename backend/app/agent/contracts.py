from __future__ import annotations

from datetime import date as CalendarDate, datetime
from decimal import Decimal
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
    REVENUE_ANALYSIS = "revenue_analysis"


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
MAXIMUM_CUSTOM_RANGE_DAYS = 400


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
        if (self.end - self.start).days + 1 > MAXIMUM_CUSTOM_RANGE_DAYS:
            raise ValueError(
                f"custom date range cannot exceed {MAXIMUM_CUSTOM_RANGE_DAYS} days"
            )
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


class RevenueAnalysisRequest(ClosedModel):
    kind: Literal["revenue_analysis"] = "revenue_analysis"
    period: EvidencePeriod | None = None
    comparison_period: EvidencePeriod | None = None
    include_percentage: bool = False


EvidenceRequestUnion = Annotated[
    EvidenceRequest
    | SettlementDetailsRequest
    | DailyLedgerRequest
    | RevenueAnalysisRequest,
    Field(discriminator="kind"),
]


class EvidencePlan(ClosedModel):
    requests: list[EvidenceRequestUnion] = Field(min_length=1, max_length=1)


class TurnRoute(StrEnum):
    CLARIFY = "clarify"
    DIRECT_ANSWER = "direct_answer"
    EVIDENCE = "evidence"
    ACTION = "action"
    SAFE_FAILURE = "safe_failure"


class OpenBusinessRecordsAction(ClosedModel):
    type: Literal["open_business_records"] = "open_business_records"
    start_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    end_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")

    @model_validator(mode="after")
    def require_allowed_ordered_months(self) -> "OpenBusinessRecordsAction":
        start = datetime.strptime(self.start_month, "%Y-%m")
        end = datetime.strptime(self.end_month, "%Y-%m")
        if not 2000 <= start.year <= 2200 or not 2000 <= end.year <= 2200:
            raise ValueError("business record months must be between 2000 and 2200")
        if start > end:
            raise ValueError("start_month must be on or before end_month")
        return self


class TurnPlan(ClosedModel):
    route: TurnRoute
    question: str | None = Field(default=None, min_length=1, max_length=2_000)
    answer: str | None = Field(default=None, min_length=1, max_length=10_000)
    evidence_plan: EvidencePlan | None = None
    supplemental_evidence_plan: EvidencePlan | None = None
    action: OpenBusinessRecordsAction | None = None
    message: str | None = Field(default=None, min_length=1, max_length=2_000)

    @model_validator(mode="after")
    def require_only_the_route_payload(self) -> "TurnPlan":
        expected = {
            TurnRoute.CLARIFY: "question",
            TurnRoute.DIRECT_ANSWER: "answer",
            TurnRoute.EVIDENCE: "evidence_plan",
            TurnRoute.ACTION: "action",
            TurnRoute.SAFE_FAILURE: "message",
        }[self.route]
        primary_payloads = {
            "question": self.question,
            "answer": self.answer,
            "evidence_plan": self.evidence_plan,
            "action": self.action,
            "message": self.message,
        }
        if primary_payloads[expected] is None or any(
            value is not None
            for name, value in primary_payloads.items()
            if name != expected
        ):
            raise ValueError(f"{self.route.value} requires only {expected}")
        if self.route != TurnRoute.EVIDENCE and self.supplemental_evidence_plan is not None:
            raise ValueError("only evidence turns may request supplemental evidence")
        if self.supplemental_evidence_plan is not None:
            supplemental_request = self.supplemental_evidence_plan.requests[0]
            if not isinstance(supplemental_request, EvidenceRequest):
                raise ValueError(
                    "supplemental evidence is limited to one business metric request"
                )
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


class RevenueAnalysisPeriodMetrics(ClosedModel):
    period: EvidencePeriodResult
    daily_ledger_revenue: int = Field(ge=0)
    confirmed_settlement_income: int = Field(ge=0)
    total_revenue: int = Field(ge=0)
    operating_days: int = Field(ge=0)
    operating_day_average_ledger_revenue: Decimal | None = Field(default=None, ge=0)


class DailyLedgerDecomposition(ClosedModel):
    status: Literal["available", "unavailable"]
    operating_days_contribution: Decimal | None = None
    operating_day_average_contribution: Decimal | None = None
    unavailable_reasons: list[str] = Field(default_factory=list, max_length=10)

    @model_validator(mode="after")
    def require_status_payload(self) -> "DailyLedgerDecomposition":
        contributions = (
            self.operating_days_contribution,
            self.operating_day_average_contribution,
        )
        if self.status == "available":
            if any(value is None for value in contributions) or self.unavailable_reasons:
                raise ValueError("available decomposition requires both contributions")
        elif any(value is not None for value in contributions) or not self.unavailable_reasons:
            raise ValueError("unavailable decomposition requires reasons only")
        return self


class RevenueCategoryChange(ClosedModel):
    category_id: int = Field(gt=0)
    category_name: str = Field(min_length=1, max_length=100)
    current_amount: int = Field(ge=0)
    comparison_amount: int = Field(ge=0)
    amount_change: int


class RevenueAnalysisResult(ClosedModel):
    current: RevenueAnalysisPeriodMetrics
    comparison: RevenueAnalysisPeriodMetrics | None
    total_revenue_change: int | None
    daily_ledger_revenue_change: int | None
    confirmed_settlement_income_change: int | None
    daily_ledger_decomposition: DailyLedgerDecomposition | None
    income_category_changes: list[RevenueCategoryChange] = Field(
        default_factory=list,
        max_length=200,
    )
    other_data_changes: list[RevenueCategoryChange] = Field(
        default_factory=list,
        max_length=200,
    )
    percentage_change: Decimal | None
    percentage_status: Literal[
        "not_requested",
        "available",
        "unavailable_zero_baseline",
        "unavailable_no_history",
    ]


class RevenueAnalysisSufficiency(ClosedModel):
    critical_data_complete: bool
    largest_verified_contribution: Literal[
        "operating_days",
        "operating_day_average",
        "confirmed_settlement_income",
    ] | None
    largest_absolute_share: Decimal | None = Field(default=None, ge=0, le=1)
    major_driver_threshold: Decimal = Field(ge=0, le=1)
    allows_mainly_from: bool


class RevenueAnalysisFindings(ClosedModel):
    verified: list[str] = Field(default_factory=list, max_length=20)
    correlated_phenomena: list[str] = Field(default_factory=list, max_length=20)
    unexplained_amount: Decimal
    unexplained: list[str] = Field(default_factory=list, max_length=20)


class RevenueAnalysisEvidenceBundle(ClosedModel):
    status: Literal["ok", "current_only"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    comparison_period: EvidencePeriodResult | None
    calculation_version: Literal["revenue_analysis.v1"] = "revenue_analysis.v1"
    result: RevenueAnalysisResult
    evidence_sufficiency: RevenueAnalysisSufficiency
    findings: RevenueAnalysisFindings
    supplemental_evidence: EvidenceBundle | None = None
    warnings: list[str] = Field(default_factory=list, max_length=20)
    summary: str = Field(min_length=1, max_length=20_000)


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


CollectedEvidence = (
    EvidenceBundle
    | SettlementDetailsEvidenceBundle
    | RevenueAnalysisEvidenceBundle
)


class TurnResult(ClosedModel):
    route: Literal["clarify", "answer", "safe_failure"]
    content: str = Field(min_length=1, max_length=20_000)
    recovery_status: Literal["none", "retried", "fallback"] = "none"
    action: OpenBusinessRecordsAction | None = None

    @model_validator(mode="after")
    def allow_actions_only_on_answers(self) -> "TurnResult":
        if self.action is not None and self.route != "answer":
            raise ValueError("actions require an answer")
        return self


class WorkflowResult(ClosedModel):
    turn: TurnResult
    evidence: CollectedEvidence | None = None
