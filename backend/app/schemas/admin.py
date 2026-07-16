from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, Field, StringConstraints


def _nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("must not be blank")
    return value.strip()


def _timezone(value: str) -> str:
    value = _nonblank(value)
    try:
        ZoneInfo(value)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("must be a valid IANA time zone") from exc
    return value


StoreName = Annotated[str, StringConstraints(max_length=120), AfterValidator(_nonblank)]
StoreAddress = Annotated[str, StringConstraints(max_length=255), AfterValidator(_nonblank)]
CategoryName = Annotated[str, StringConstraints(max_length=100), AfterValidator(_nonblank)]
TimeZoneName = Annotated[str, StringConstraints(max_length=64), AfterValidator(_timezone)]
Latitude = Annotated[Decimal, Field(ge=-90, le=90)]
Longitude = Annotated[Decimal, Field(ge=-180, le=180)]


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"


class UserPatch(BaseModel):
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    store_ids: list[int] | None = None


class StoreCreate(BaseModel):
    name: StoreName
    address: StoreAddress
    latitude: Latitude
    longitude: Longitude
    timezone: TimeZoneName = "Europe/Rome"


class StorePatch(BaseModel):
    name: StoreName | None = None
    address: StoreAddress | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    timezone: TimeZoneName | None = None
    is_active: bool | None = None


class MemberReplace(BaseModel):
    user_ids: list[int]


class CategoryCreate(BaseModel):
    store_id: int
    name: CategoryName
    include_in_total: bool
    sort_order: int = 0


class CategoryPatch(BaseModel):
    name: CategoryName | None = None
    include_in_total: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None
