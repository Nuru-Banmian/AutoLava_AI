from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, model_validator

from app.models.operations import UTC_TIMESTAMP_CONTRACT
from app.schemas.time import trusted_utc


class DashboardCardResponse(BaseModel):
    card_type: Literal["yesterday", "today", "tomorrow"]
    state: Literal["missing", "recorded", "rest", "weather_closed", "forecast", "unavailable"]
    revenue: int | None = None
    weather: str | None = None
    weekday: str | None = None
    temperature_max: Decimal | None = None
    temperature_min: Decimal | None = None
    precipitation: Decimal | None = None
    hint: str | None = None
    generated_at: datetime | None = None
    timestamp_status: Literal["utc", "legacy_unknown"] = "legacy_unknown"

    @model_validator(mode="after")
    def generated_at_matches_source_contract(self) -> "DashboardCardResponse":
        contract = UTC_TIMESTAMP_CONTRACT if self.timestamp_status == "utc" else "legacy_unknown"
        self.generated_at = trusted_utc(self.generated_at, contract)
        return self
