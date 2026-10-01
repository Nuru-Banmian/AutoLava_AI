from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class AuthenticatedUserResponse(BaseModel):
    id: int
    username: str
    role: Literal["admin", "user"]
    is_owner: bool


class AccessibleStoreResponse(BaseModel):
    id: int
    name: str
    timezone: str
    is_active: bool
    company_settlement_enabled: bool
    wash_count_enabled: bool


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=8, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)
