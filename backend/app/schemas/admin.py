from datetime import datetime
from decimal import Decimal
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import AfterValidator, BaseModel, Field, StrictInt, StringConstraints, field_validator


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
StoreDescription = Annotated[
    str,
    StringConstraints(max_length=3000),
    AfterValidator(lambda value: value if value.strip() else ""),
]


class UserCreate(BaseModel):
    editor_ids: list[StrictInt] = Field(default_factory=list)
    manager_id: int | None = None
    username: str = Field(min_length=3, max_length=80)
    password: str = Field(min_length=8, max_length=128)
    role: Literal["admin", "user"] = "user"
    store_ids: list[int] = Field(default_factory=list)


class UserPatch(BaseModel):
    editor_ids: list[StrictInt] | None = None
    manager_id: int | None = None
    password: str | None = Field(default=None, min_length=8, max_length=128)
    role: Literal["admin", "user"] | None = None
    is_active: bool | None = None
    store_ids: list[int] | None = None


class StoreCreate(BaseModel):
    name: StoreName
    description: StoreDescription = ""
    address: StoreAddress
    latitude: Latitude
    longitude: Longitude
    timezone: TimeZoneName = "Europe/Rome"
    wash_count_enabled: bool = True


class StorePatch(BaseModel):
    description: StoreDescription | None = None
    expected_description_revision: StrictInt | None = Field(default=None, ge=1)
    name: StoreName | None = None
    address: StoreAddress | None = None
    latitude: Latitude | None = None
    longitude: Longitude | None = None
    timezone: TimeZoneName | None = None
    is_active: bool | None = None
    company_settlement_enabled: bool | None = None
    wash_count_enabled: bool | None = None

    @field_validator("description", mode="before")
    @classmethod
    def description_not_null(cls, value):
        if value is None:
            raise ValueError("门店描述不能为 null；清空请使用空字符串")
        return value


class MemberReplace(BaseModel):
    user_ids: list[int]


class CategoryCreate(BaseModel):
    expected_revision: int | None = None
    store_id: int
    name: CategoryName
    include_in_total: bool
    sort_order: int = 0


class CategoryPatch(BaseModel):
    expected_revision: int | None = None
    name: CategoryName | None = None
    include_in_total: bool | None = None
    is_active: bool | None = None
    sort_order: int | None = None


class AdminUserResponse(BaseModel):
    creator_id: int | None = None
    editor_ids: list[int] = Field(default_factory=list)
    can_manage_editors: bool | None = None
    manager_id: int | None = None
    id: int
    username: str
    role: Literal["admin", "user"]
    is_active: bool
    store_ids: list[int]


class UserSummaryResponse(BaseModel):
    id: int
    username: str
    role: Literal["admin", "user"]
    is_active: bool


class AdminStoreResponse(BaseModel):
    id: int
    description: str
    description_revision: int
    name: str
    address: str
    latitude: str | None
    longitude: str | None
    timezone: str
    is_active: bool
    company_settlement_enabled: bool
    wash_count_enabled: bool


class StoreMembersResponse(BaseModel):
    store_id: int
    user_ids: list[int]


class SystemAlertResponse(BaseModel):
    id: int
    store_id: int | None
    alert_type: str
    level: str
    message: str
    is_resolved: bool
    created_at: datetime | None
    resolved_at: datetime | None
    timestamp_status: Literal["utc", "legacy_unknown"]


class ScheduledTaskLogResponse(BaseModel):
    id: int
    store_id: int | None
    task_type: str
    status: str
    message: str | None
    retry_count: int
    started_at: datetime | None
    finished_at: datetime | None
    created_at: datetime | None
    timestamp_status: Literal["utc", "legacy_unknown"]


class GeocodeCandidateResponse(BaseModel):
    name: str
    country: str
    latitude: float
    longitude: float
    timezone: str


class TimezoneResponse(BaseModel):
    timezone: str
