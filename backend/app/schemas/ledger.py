from enum import Enum
from typing import Annotated, Literal

from pydantic import BaseModel, Field

from app.services.weather import WMO_WEATHER_LABELS

MoneyAmount = Annotated[int, Field(strict=True, ge=0, le=9_999_999_999)]
RecordWeather = Enum(
    "RecordWeather",
    {f"WMO_{code}": label for code, label in WMO_WEATHER_LABELS.items()},
    type=str,
)


class IncomeItemBody(BaseModel):
    category_id: int
    amount: MoneyAmount


class LedgerBody(BaseModel):
    is_open: Literal["营业", "休息", "提前休息"]
    daily_revenue: MoneyAmount | None = None
    wash_count: int | None = Field(default=None, ge=0)
    weather: RecordWeather | None = None
    weather_edited: bool = False
    activity: str | None = Field(default=None, max_length=2000)
    items: list[IncomeItemBody] = []
