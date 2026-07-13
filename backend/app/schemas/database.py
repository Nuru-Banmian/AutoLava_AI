from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class DatabaseFilters(BaseModel):
    start: date | None = None
    end: date | None = None
    status: Literal["营业", "休息", "天气停业"] | None = None
    weather: str | None = Field(default=None, max_length=50)
    activity_query: str | None = Field(default=None, max_length=2000)
    missing_wash_count: bool = False


class CategoryDescriptor(BaseModel):
    id: int
    name: str
    include_in_total: bool
    is_active: bool
    sort_order: int


class DatabasePage(BaseModel):
    items: list[dict]
    categories: list[CategoryDescriptor]
    sum_daily_revenue: str
    total: int
    page: int
    page_size: int


class RollbackResult(BaseModel):
    audit_id: int
    record: dict | None
