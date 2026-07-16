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


class ChartsResponse(BaseModel):
    kpis: ChartKpis
    daily: list[DailyRevenue]
    categories: list[CategoryComposition]
    monthly: list[MonthlyRevenue]
    weather: list[WeatherRevenue]
    weekday: list[WeekdayRevenue]
