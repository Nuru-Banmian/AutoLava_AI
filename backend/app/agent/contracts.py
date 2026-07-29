from __future__ import annotations

from datetime import date as CalendarDate, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

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
    DAILY_LEDGER_DRILLDOWN = "daily_ledger_drilldown"
    EVENT_INVESTIGATION = "event_investigation"
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
    EVENT_INVESTIGATION = "event_investigation"


class EventTypeCode(StrEnum):
    ACCESS_DISRUPTION = "access_disruption"
    EQUIPMENT_ISSUE = "equipment_issue"
    LOCAL_EVENT = "local_event"
    PROMOTION = "promotion"
    SCHEDULE_CHANGE = "schedule_change"
    STAFFING_ISSUE = "staffing_issue"
    WEATHER_DISRUPTION = "weather_disruption"


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
    EvidenceMetric.EVENT_INVESTIGATION: "事件调查",
}
SETTLEMENT_DETAILS_LABEL = "公司结算明细"
MONTHLY_TOTAL_REVENUE_LABEL = "月度总收入"
DAILY_LEDGER_LABEL = "每日台账"
MINIMUM_EVIDENCE_DATE = CalendarDate(2000, 1, 1)
MAXIMUM_EVIDENCE_DATE = CalendarDate(2200, 12, 31)
MAXIMUM_CUSTOM_RANGE_DAYS = 400
MAX_DAILY_LEDGER_DRILLDOWN_DATES = 31
MAX_DAILY_LEDGER_DETAIL_ROWS = 10


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
            raise ValueError(f"custom date range cannot exceed {MAXIMUM_CUSTOM_RANGE_DAYS} days")
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
        if self.comparison is not None and self.metric != EvidenceMetric.MONTHLY_TOTAL_REVENUE:
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
            if self.group_by == EvidenceGroup.INCOME_CATEGORY and self.metric not in {
                EvidenceMetric.DAILY_LEDGER_REVENUE,
                EvidenceMetric.INCOME_CATEGORY_AMOUNT,
                EvidenceMetric.OTHER_DATA_AMOUNT,
            }:
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


class DailyLedgerDrilldownRequest(ClosedModel):
    kind: Literal["daily_ledger_drilldown"] = "daily_ledger_drilldown"
    dates: list[CalendarDate] = Field(
        min_length=1,
        max_length=MAX_DAILY_LEDGER_DRILLDOWN_DATES,
    )

    @field_validator("dates")
    @classmethod
    def require_unique_dates(cls, values: list[CalendarDate]) -> list[CalendarDate]:
        if len(values) != len(set(values)):
            raise ValueError("daily ledger drilldown dates must be unique")
        return values


class EventInvestigationRequest(ClosedModel):
    kind: Literal["event_investigation"] = "event_investigation"
    period: CalendarMonthPeriod


BusinessEvidenceRequest = Annotated[
    EvidenceRequest
    | SettlementDetailsRequest
    | DailyLedgerRequest
    | DailyLedgerDrilldownRequest
    | EventInvestigationRequest,
    Field(discriminator="kind"),
]


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
    missing_fields: list[Literal["recorded_weather", "wash_count"]] = Field(default_factory=list)
    unavailable_fields: list[Literal["wash_count"]] = Field(default_factory=list)
    raw_event: UntrustedRawEvent | None = None


class DailyLedgerDrilldownResult(ClosedModel):
    detail_status: Literal["details", "navigation_required"]
    records: list[DailyLedgerResult] = Field(
        default_factory=list,
        max_length=MAX_DAILY_LEDGER_DETAIL_ROWS,
    )
    unrecorded_dates: list[CalendarDate] = Field(
        default_factory=list,
        max_length=MAX_DAILY_LEDGER_DRILLDOWN_DATES,
    )
    matched_records: int = Field(ge=0, le=MAX_DAILY_LEDGER_DRILLDOWN_DATES)
    suggested_action: OpenBusinessRecordsAction | None = None

    @model_validator(mode="after")
    def require_bounded_detail_shape(self) -> "DailyLedgerDrilldownResult":
        if self.detail_status == "details":
            if self.matched_records != len(self.records) or self.suggested_action is not None:
                raise ValueError("daily ledger details require every matched record")
        elif self.records or self.suggested_action is None:
            raise ValueError("truncated daily ledger results require a navigation suggestion")
        return self


class EventType(ClosedModel):
    code: EventTypeCode
    name: str = Field(min_length=1, max_length=50)


class EventObservation(ClosedModel):
    date: CalendarDate
    daily_revenue: int = Field(ge=0)
    operating_status: Literal["营业", "休息", "提前休息"]
    recorded_weather: str | None = Field(default=None, max_length=50)
    wash_count: int | None = Field(default=None, ge=0)
    raw_event: UntrustedRawEvent
    classification_status: Literal["classified", "unclassified"]
    event_types: list[EventType] = Field(max_length=7)
    store_event_identifier: str | None = Field(
        default=None,
        pattern=r"^store_event_[0-9a-f]{16}$",
    )
    source_record_id: int = Field(gt=0)
    source_event_fingerprint: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    analysis_version: Literal["event_type_rules.v1"]

    @model_validator(mode="after")
    def require_classification_shape(self) -> "EventObservation":
        codes = [event_type.code for event_type in self.event_types]
        if len(codes) != len(set(codes)):
            raise ValueError("event types must be unique")
        if (self.classification_status == "classified") != bool(self.event_types):
            raise ValueError("event classification status must match its types")
        return self


class EventInvestigationResult(ClosedModel):
    observations: list[EventObservation] = Field(max_length=31)
    classified_events: int = Field(ge=0, le=31)
    unclassified_events: int = Field(ge=0, le=31)

    @model_validator(mode="after")
    def require_event_counts(self) -> "EventInvestigationResult":
        if self.classified_events + self.unclassified_events != len(self.observations):
            raise ValueError("event investigation counts must match observations")
        if len({observation.date for observation in self.observations}) != len(self.observations):
            raise ValueError("event investigation dates must be unique")
        return self


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
    | DailyLedgerDrilldownResult
    | EventInvestigationResult
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


class ExternalGeographicScope(ClosedModel):
    kind: Literal["coordinates", "country"]
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    country_code: Literal["IT"]

    @model_validator(mode="after")
    def require_scope_shape(self) -> "ExternalGeographicScope":
        coordinates = (self.latitude, self.longitude)
        if self.kind == "coordinates" and (
            any(value is None for value in coordinates) or self.timezone is None
        ):
            raise ValueError("coordinate scope requires coordinates and timezone")
        if self.kind == "country" and any(value is not None for value in coordinates):
            raise ValueError("country scope cannot contain coordinates")
        return self


class ExternalEvidenceCoverage(EvidenceCoverage):
    missing_dates: list[CalendarDate] = Field(default_factory=list, max_length=366)


class ExternalEvidenceFreshness(ClosedModel):
    status: Literal["fresh", "stale", "unavailable"]
    as_of: datetime | None = None
    max_age_seconds: int = Field(ge=1)
    cache_status: Literal["miss", "fresh", "refreshed", "stale_fallback"]
    refresh_failure: (
        Literal[
            "timeout",
            "rate_limited",
            "service_unavailable",
            "invalid_response",
        ]
        | None
    ) = None

    @model_validator(mode="after")
    def require_freshness_shape(self) -> "ExternalEvidenceFreshness":
        if self.status == "fresh" and (
            self.as_of is None
            or self.cache_status == "stale_fallback"
            or self.refresh_failure is not None
        ):
            raise ValueError("fresh evidence requires a current source snapshot")
        if self.status == "stale" and (
            self.as_of is None
            or self.cache_status != "stale_fallback"
            or self.refresh_failure is None
        ):
            raise ValueError("stale evidence requires a failed refresh")
        if self.status == "unavailable" and (
            self.as_of is not None or self.cache_status != "miss" or self.refresh_failure is None
        ):
            raise ValueError("unavailable evidence requires an explicit provider failure")
        return self


class ExternalEvidenceFailure(ClosedModel):
    status: Literal["none", "failed"]
    category: (
        Literal[
            "timeout",
            "rate_limited",
            "service_unavailable",
            "invalid_response",
        ]
        | None
    ) = None
    message: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def require_failure_shape(self) -> "ExternalEvidenceFailure":
        details = (self.category, self.message)
        if self.status == "none" and any(value is not None for value in details):
            raise ValueError("successful external evidence cannot contain failure details")
        if self.status == "failed" and any(value is None for value in details):
            raise ValueError("failed external evidence requires category and message")
        return self


class ExternalEvidenceBundle(ClosedModel):
    status: Literal["ok", "failed"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    evidence_type: Literal["historical_weather", "public_holidays"]
    external_evidence: Literal[True] = True
    unit: Literal["external_fact"] = "external_fact"
    source: Literal["open_meteo_historical", "nager_date_public_holidays"]
    queried_at: datetime
    geographic_scope: ExternalGeographicScope
    coverage: ExternalEvidenceCoverage
    freshness: ExternalEvidenceFreshness
    failure: ExternalEvidenceFailure
    result: dict[str, Any]
    warnings: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool = False

    @model_validator(mode="after")
    def require_external_evidence_shape(self) -> "ExternalEvidenceBundle":
        if self.status == "ok" and (
            self.failure.status != "none" or self.freshness.status == "unavailable"
        ):
            raise ValueError("available external evidence cannot contain a terminal failure")
        if self.status == "failed" and (
            self.failure.status != "failed"
            or self.freshness.status != "unavailable"
            or self.result
            or self.coverage.recorded_dates
        ):
            raise ValueError("failed external evidence cannot contain facts")
        return self


class EvidenceBundle(ClosedModel):
    status: Literal["ok", "not_recorded"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    metric: EvidenceMetric
    group_by: EvidenceGroup | None = None
    filters: EvidenceFilters | None = None
    extreme: Literal["highest", "lowest"] | None = None
    selected_dates: list[CalendarDate] | None = Field(
        default=None,
        max_length=MAX_DAILY_LEDGER_DRILLDOWN_DATES,
        exclude_if=lambda value: value is None,
    )
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
        "daily_ledger_drilldown.v1",
        "event_investigation.v1",
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
        if self.metric == EvidenceMetric.EVENT_INVESTIGATION:
            if (
                self.status != "ok"
                or self.unit != "mixed"
                or self.calculation_version != "event_investigation.v1"
                or not isinstance(self.result, EventInvestigationResult)
                or self.group_by is not None
                or self.filters is not None
                or self.extreme is not None
                or self.selected_dates is not None
                or self.comparison is not None
                or self.coverage.recorded_dates != len(self.result.observations)
                or self.coverage.calendar_dates != (self.period.end - self.period.start).days + 1
                or any(
                    observation.date < self.period.start or observation.date > self.period.end
                    for observation in self.result.observations
                )
            ):
                raise ValueError("event investigation evidence has an inconsistent shape")
            return self
        if self.metric != EvidenceMetric.DAILY_LEDGER:
            if (
                self.status != "ok"
                or self.unit == "mixed"
                or self.calculation_version in {"daily_ledger.v1", "daily_ledger_drilldown.v1"}
                or isinstance(self.result, (DailyLedgerResult, DailyLedgerDrilldownResult))
                or self.selected_dates is not None
            ):
                raise ValueError("business metric evidence has an inconsistent shape")
            return self
        if self.calculation_version == "daily_ledger_drilldown.v1":
            if not isinstance(self.result, DailyLedgerDrilldownResult):
                raise ValueError("daily ledger drilldown evidence has an inconsistent shape")
            recorded_dates = {
                row.facts.date for row in self.result.records if row.facts is not None
            }
            if (
                self.status != "ok"
                or self.unit != "mixed"
                or not self.selected_dates
                or len(self.selected_dates) != len(set(self.selected_dates))
                or self.period.start != min(self.selected_dates)
                or self.period.end != max(self.selected_dates)
                or self.coverage.calendar_dates != len(self.selected_dates)
                or self.coverage.recorded_dates != self.result.matched_records
                or len(recorded_dates) != len(self.result.records)
                or any(
                    row.facts is None or row.facts.date not in self.selected_dates
                    for row in self.result.records
                )
                or any(value not in self.selected_dates for value in self.result.unrecorded_dates)
                or (
                    self.result.detail_status == "details"
                    and (
                        recorded_dates.intersection(self.result.unrecorded_dates)
                        or recorded_dates.union(self.result.unrecorded_dates)
                        != set(self.selected_dates)
                    )
                )
            ):
                raise ValueError("daily ledger drilldown evidence has an inconsistent shape")
            return self
        if (
            self.unit != "mixed"
            or self.calculation_version != "daily_ledger.v1"
            or not isinstance(self.result, DailyLedgerResult)
            or self.group_by is not None
            or self.filters is not None
            or self.extreme is not None
            or self.comparison is not None
            or self.selected_dates is not None
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


class SettlementDetailsQueryScope(ClosedModel):
    status: Literal["pending", "confirmed"] | None = None
    company_name: SettlementCompanyName | None = None


class SettlementDetailsEvidenceBundle(ClosedModel):
    status: Literal["ok", "refused"]
    current_store: CurrentStoreScope
    period: EvidencePeriodResult
    evidence_type: Literal["settlement_details"] = "settlement_details"
    unit: Literal["EUR"] = "EUR"
    calculation_version: Literal["settlement_details.v1"] = "settlement_details.v1"
    query_scope: SettlementDetailsQueryScope = Field(default_factory=SettlementDetailsQueryScope)
    result: SettlementDetailsResult
    warnings: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool = False


CollectedEvidence = EvidenceBundle | SettlementDetailsEvidenceBundle | ExternalEvidenceBundle


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
