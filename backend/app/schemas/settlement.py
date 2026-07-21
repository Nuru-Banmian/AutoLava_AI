import re
from datetime import date
from typing import Annotated

from pydantic import BaseModel, BeforeValidator, Field, StringConstraints


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
    company_id: int
    opening_month: str
    amount: int = Field(gt=0)


class RecordPatch(BaseModel):
    company_id: int | None = None
    amount: int | None = Field(default=None, gt=0)
    revision: int = Field(gt=0)


class RevisionBody(BaseModel):
    revision: int = Field(gt=0)
