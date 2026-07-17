from typing import Literal

from pydantic import BaseModel


class PrimaryCategory(BaseModel):
    category_id: int
    category_name: str
    amount: str


class ChartKpis(BaseModel):
    total_revenue: str
    record_days: int
    open_days: int
    average_revenue: str
    primary_categories: list[PrimaryCategory]
    total_wash_count: int | None
    average_ticket: str | None


class DailyRevenue(BaseModel):
    date: str
    revenue: str


class CategoryComposition(PrimaryCategory):
    pass


class MonthlyRevenue(BaseModel):
    month: str
    revenue: str


class WeatherRevenue(BaseModel):
    weather: str
    average_revenue: str


class WeekdayRevenue(BaseModel):
    weekday: int
    average_revenue: str


class ChartRange(BaseModel):
    start: str
    end: str
    bucket: Literal["day", "month"]


class ChartComparisonKpis(BaseModel):
    start: str
    end: str
    total_revenue: str
    open_days: int
    average_revenue: str


class ChartsResponse(BaseModel):
    kpis: ChartKpis
    range: ChartRange
    comparison_kpis: ChartComparisonKpis | None
    classified_included_total: str
    daily: list[DailyRevenue]
    categories: list[CategoryComposition]
    excluded_categories: list[CategoryComposition]
    monthly: list[MonthlyRevenue]
    weather: list[WeatherRevenue]
    weekday: list[WeekdayRevenue]
