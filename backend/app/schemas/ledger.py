from typing import Annotated, Literal

from pydantic import BaseModel, Field

MoneyAmount = Annotated[int, Field(strict=True, ge=0, le=9_999_999_999)]


class IncomeItemBody(BaseModel):
    category_id: int
    amount: MoneyAmount


class LedgerBody(BaseModel):
    is_open: Literal["营业", "休息", "天气停业"]
    daily_revenue: MoneyAmount | None = None
    wash_count: int | None = Field(default=None, ge=0)
    weather: str | None = Field(default=None, max_length=50)
    weather_edited: bool = False
    activity: str | None = Field(default=None, max_length=2000)
    items: list[IncomeItemBody] = []
