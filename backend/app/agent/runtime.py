from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class RuntimeFeatureFlags(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_enabled: bool
    company_settlement_enabled: bool
    income_items_enabled: bool
    wash_count_enabled: bool


class RuntimeContext(BaseModel):
    """Server-owned identity, store scope, timezone, and live feature flags."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    user_id: int
    store_id: int
    role: Literal["admin", "final_admin"]
    store_timezone: str
    store_latitude: float | None = Field(default=None, ge=-90, le=90)
    store_longitude: float | None = Field(default=None, ge=-180, le=180)
    store_country_code: Literal["IT"] | None = None
    features: RuntimeFeatureFlags
