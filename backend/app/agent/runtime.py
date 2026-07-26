from typing import Literal

from pydantic import BaseModel, ConfigDict


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
    features: RuntimeFeatureFlags
