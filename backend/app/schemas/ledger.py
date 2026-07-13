from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class IncomeItemBody(BaseModel):
    category_id: int
    amount: Decimal = Field(ge=0, max_digits=12, decimal_places=2)


class LedgerBody(BaseModel):
    is_open: Literal["营业", "休息", "天气停业"]
    wash_count: int | None = Field(default=None, ge=0)
    weather: str | None = Field(default=None, max_length=50)
    weather_edited: bool = False
    activity: str | None = Field(default=None, max_length=2000)
    items: list[IncomeItemBody]
