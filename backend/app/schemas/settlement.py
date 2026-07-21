import re
from datetime import date, datetime
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    BeforeValidator,
    Field,
    StrictInt,
    StringConstraints,
    field_serializer,
    model_validator,
)


def _name(value: str) -> str:
    value = " ".join(value.split())
    if not value:
        raise ValueError("must not be blank")
    return value


def parse_month(value: str) -> date:
    if not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", value):
        raise ValueError("month must use YYYY-MM")
    return date(int(value[:4]), int(value[5:]), 1)


CompanyName = Annotated[
    str,
    BeforeValidator(_name),
    StringConstraints(min_length=1, max_length=120),
]
MAX_SETTLEMENT_AMOUNT = 9_999_999_999


class CompanyResponse(BaseModel):
    id: int
    name: str
    is_active: bool

    model_config = {"from_attributes": True}


class CompanyCreate(BaseModel):
    name: CompanyName


class CompanyPatch(BaseModel):
    name: CompanyName


class RecordCreate(BaseModel):
    company_id: StrictInt = Field(gt=0)
    opening_month: str
    amount: StrictInt = Field(gt=0, le=MAX_SETTLEMENT_AMOUNT)


class SettlementRecordResponse(BaseModel):
    id: int
    company_id: int
    company_name: str
    opening_month: date
    amount: int
    status: Literal["pending", "confirmed"]
    revision: int
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_serializer("opening_month")
    def serialize_opening_month(self, value: date) -> str:
        return value.strftime("%Y-%m")


class SettlementMonthResponse(BaseModel):
    opening_month: date
    records: list[SettlementRecordResponse]
    daily_ledger_revenue: int
    confirmed_settlement_income: int
    pending_amount: int
    monthly_total: int

    @field_serializer("opening_month")
    def serialize_opening_month(self, value: date) -> str:
        return value.strftime("%Y-%m")


class RecordPatch(BaseModel):
    company_id: StrictInt | None = Field(default=None, gt=0)
    amount: StrictInt | None = Field(default=None, gt=0, le=MAX_SETTLEMENT_AMOUNT)
    revision: StrictInt = Field(gt=0)

    @model_validator(mode="after")
    def requires_change(self) -> "RecordPatch":
        if self.company_id is None and self.amount is None:
            raise ValueError("company_id or amount is required")
        return self


class RevisionBody(BaseModel):
    revision: StrictInt = Field(gt=0)
