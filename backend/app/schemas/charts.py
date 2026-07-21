from typing import Literal

from pydantic import BaseModel


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
    average_ticket: int | None


class DailyRevenue(BaseModel):
    date: str
    revenue: int


class CategoryComposition(PrimaryCategory):
    pass


class MonthlyRevenue(BaseModel):
    month: str
    revenue: int
    daily_ledger_revenue: int
    confirmed_settlement_income: int | None
    monthly_total_income: int | None


class IncomeSummary(BaseModel):
    daily_ledger_revenue: int
    confirmed_settlement_income: int
    total_income: int
    includes_settlement_income: bool


class WeatherRevenue(BaseModel):
    weather: str
    average_revenue: int


class WeekdayRevenue(BaseModel):
    weekday: int
    average_revenue: int


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
    categories: list[CategoryComposition]
    excluded_categories: list[CategoryComposition]
    monthly: list[MonthlyRevenue]
    weather: list[WeatherRevenue]
    weekday: list[WeekdayRevenue]
