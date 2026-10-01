from typing import Annotated

from fastapi import APIRouter, Body, Depends

from app.api.deps import Session, require_admin, require_capability
from app.models.identity import User
from app.schemas.income_config import (
    IncomeCategoryResponse,
    IncomeConfigPublishBody,
    IncomeConfigResponse,
    IncomeCategoryVersionBody,
)
from app.services.income_config import IncomeConfigCommands, IncomeConfigService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
IncomeConfigManager = Annotated[
    User, Depends(require_capability("income_config.manage"))
]


@router.get("/stores/{store_id}/income-config", response_model=IncomeConfigResponse)
async def get_income_config(store_id: int, session: Session) -> IncomeConfigResponse:
    service = IncomeConfigService(session)
    return await service.current(store_id)


@router.put("/stores/{store_id}/income-config", response_model=IncomeConfigResponse)
async def put_income_config(
    store_id: int,
    body: IncomeConfigPublishBody,
    session: Session,
    actor: IncomeConfigManager,
) -> IncomeConfigResponse:
    return await IncomeConfigCommands(session, actor.id).replace(store_id, body)


@router.post("/income-categories/{category_id}/archive", response_model=IncomeCategoryResponse)
async def archive_income_category(
    category_id: int, session: Session, actor: IncomeConfigManager,
    body: IncomeCategoryVersionBody | None = Body(default=None),
) -> IncomeCategoryResponse:
    return await IncomeConfigCommands(session, actor.id).change_category(
        category_id, body.expected_revision if body else None, restore=False
    )


@router.post("/income-categories/{category_id}/restore", response_model=IncomeCategoryResponse)
async def restore_income_category(
    category_id: int, session: Session, actor: IncomeConfigManager,
    body: IncomeCategoryVersionBody | None = Body(default=None),
) -> IncomeCategoryResponse:
    return await IncomeConfigCommands(session, actor.id).change_category(
        category_id, body.expected_revision if body else None, restore=True
    )
