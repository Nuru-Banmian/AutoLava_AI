from typing import Literal

from pydantic import BaseModel, Field


class PrimaryCategory(BaseModel):
    category_id: int
    category_name: str
    amount: int


class ChartKpis(BaseModel):
    total_revenue: int
    record_days: int
    open_days: int
    average_revenue: int
    primary_categories: list[PrimaryCategory]
    total_wash_count: int | None
    wash_count_covered_days: int | None
    wash_count_coverage_status: Literal["no_operating_days", "missing", "partial", "complete"] | None
    average_ticket: int | None


class DailyRevenue(BaseModel):
    date: str
    revenue: int | None
    is_open: Literal["营业", "休息", "提前休息", "未统计"] | None = None


class PeriodCoverage(BaseModel):
    start: str
    end: str
    record_days: int
    interval_days: int
    statistical_days: int = 0
    unreported_days: int = 0
    operating_days: int = 0
    rest_days: int = 0
    missing_record_days: int = 0


class LedgerComparison(BaseModel):
    current_revenue: int
    previous_revenue: int | None
    change_percent: float | None
    status: Literal[
        "comparable", "no_previous_records", "zero_previous", "no_comparison", "no_current_records"
    ]
    short_previous_month: bool


class SettlementComposition(BaseModel):
    category_id: None = None
    category_name: Literal["公司结算"]
    amount: int


class UnclassifiedComposition(BaseModel):
    category_id: None = None
    category_name: Literal["未分类营业额"]
    amount: int


CategoryComposition = PrimaryCategory | SettlementComposition
IncomeComposition = CategoryComposition | UnclassifiedComposition


class MonthlyRevenue(BaseModel):
    month: str
    revenue: int | None
    daily_ledger_revenue: int | None
    confirmed_settlement_income: int
    monthly_total_income: int | None


class IncomeSummary(BaseModel):
    daily_ledger_revenue: int
    confirmed_settlement_income: int
    total_income: int
    includes_settlement_income: bool


class WeatherRevenue(BaseModel):
    weather: str
    average_revenue: int
    operating_day_count: int = Field(ge=0)


class WeekdayRevenue(BaseModel):
    weekday: int
    average_revenue: int
    operating_day_count: int = Field(ge=0)


class ChartRange(BaseModel):
    start: str
    end: str
    bucket: Literal["day", "month"]


class ChartComparisonKpis(BaseModel):
    start: str
    end: str
    total_revenue: int
    open_days: int
    average_revenue: int


class ChartsResponse(BaseModel):
    kpis: ChartKpis
    range: ChartRange
    comparison_kpis: ChartComparisonKpis | None
    income_summary: IncomeSummary
    classified_included_total: int
    daily: list[DailyRevenue]
    period_coverage: PeriodCoverage | None = None
    comparison_daily: list[DailyRevenue] = Field(default_factory=list)
    comparison_coverage: PeriodCoverage | None = None
    ledger_comparison: LedgerComparison | None = None
    categories: list[CategoryComposition]
    income_composition: list[IncomeComposition] = Field(default_factory=list)
    excluded_categories: list[CategoryComposition]
    monthly: list[MonthlyRevenue]
    weather: list[WeatherRevenue]
    weekday: list[WeekdayRevenue]
