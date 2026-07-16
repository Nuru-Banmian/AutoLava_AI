from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel


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
