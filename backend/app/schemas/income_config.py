from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.schemas.admin import CategoryName


class IncomeConfigItemBody(BaseModel):
    category_id: int | None = None
    name: CategoryName
    include_in_total: bool
    is_active: bool = True
    sort_order: int = 0


class IncomeConfigPublishBody(BaseModel):
    enabled: bool
    items: list[IncomeConfigItemBody]


class IncomeConfigResponse(BaseModel):
    store_id: int
    enabled: bool
    formula: str
    items: list["IncomeCategoryResponse"]


class IncomeCategoryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    store_id: int
    name: str
    include_in_total: bool
    is_active: bool
    sort_order: int
    archived_at: datetime | None
