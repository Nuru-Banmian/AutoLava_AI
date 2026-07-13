from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    is_active: bool | None = None


class StoreCreate(BaseModel):
    name: str
    address: str
    latitude: Decimal
    longitude: Decimal
    timezone: str = "Europe/Rome"


class StorePatch(BaseModel):
    name: str | None = None
    address: str | None = None
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    timezone: str | None = None
    is_active: bool | None = None


class MemberReplace(BaseModel):
    user_ids: list[int]


class CategoryCreate(BaseModel):
    store_id: int
    name: str
    include_in_total: bool
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: str | None = None
    include_in_total: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
