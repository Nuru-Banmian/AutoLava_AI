from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class DatabaseFilters(BaseModel):
    start: date | None = None
    end: date | None = None
    status: Literal["营业", "休息", "提前休息", "未统计"] | None = None
    weather: str | None = Field(default=None, max_length=50)
    activity_query: str | None = Field(default=None, max_length=2000)
    missing_wash_count: bool = False


class CategoryDescriptor(BaseModel):
    id: int
    name: str
    include_in_total: bool
    is_active: bool
    sort_order: int


class RecordItem(BaseModel):
    id: int
    category_id: int
    category_name: str
    include_in_total: bool
    sort_order: int
    amount: int
    created_at: str
    updated_at: str


class BookkeepingEvent(BaseModel):
    id: int
    action: Literal["created", "updated"]
    actor_id: int
    actor_name: str
    occurred_at: datetime | None
    timestamp_status: Literal["utc", "legacy_unknown"]


class RecordSnapshot(BaseModel):
    id: int
    identity: str
    revision: int
    config_revision: int | None = None
    store_id: int
    date: str
    daily_revenue: int | None
    wash_count: int | None = None
    is_open: Literal["营业", "休息", "提前休息", "未统计"]
    income_mode: Literal["legacy_total", "composed"]
    weather: str | None
    weather_legacy: bool
    weather_auto: str | None
    weather_code: int | None
    temperature_max: Decimal | None
    temperature_min: Decimal | None
    precipitation: Decimal | None
    activity: str | None
    weather_edited: bool
    scanned: bool
    created_by: int
    updated_by: int
    created_at: str
    updated_at: str
    items: list[RecordItem]
    created_by_name: str | None = None
    updated_by_name: str | None = None
    bookkeeping_events: list[BookkeepingEvent] | None = None


class DatabasePage(BaseModel):
    items: list[RecordSnapshot]
    categories: list[CategoryDescriptor]
    sum_daily_revenue: int
    total: int
    page: int
    page_size: int
