from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, field_validator

from app.schemas.time import as_utc


class DashboardCardResponse(BaseModel):
    card_type: Literal["yesterday", "today", "tomorrow"]
    state: Literal["missing", "recorded", "rest", "weather_closed", "forecast", "unavailable"]
    revenue: Decimal | None = None
    weather: str | None = None
    weekday: str | None = None
    temperature_max: Decimal | None = None
    temperature_min: Decimal | None = None
    precipitation: Decimal | None = None
    hint: str | None = None
    generated_at: datetime

    @field_validator("generated_at")
    @classmethod
    def generated_at_is_explicit_utc(cls, value: datetime) -> datetime:
        normalized = as_utc(value)
        assert normalized is not None
        return normalized
