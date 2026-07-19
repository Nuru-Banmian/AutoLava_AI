from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Session, require_admin, require_capability
from app.core.database import sqlite_short_write
from app.models.identity import User
from app.models.ledger import IncomeCategory
from app.schemas.income_config import (
    IncomeCategoryResponse,
    IncomeConfigPublishBody,
    IncomeConfigResponse,
)
from app.services.income_config import IncomeConfigService
from app.services.access import require_fresh_store_access

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
    actor_id = actor.id
    async with sqlite_short_write(session):
        await require_fresh_store_access(
            session,
            user_id=actor_id,
            store_id=store_id,
            capability="income_config.manage",
        )
        response = await IncomeConfigService(session).replace(store_id, body)
    return response


async def _fresh_category_manager(
    session: Session, *, actor_id: int, category_id: int
) -> IncomeCategory:
    category = await session.get(
        IncomeCategory, category_id, populate_existing=True
    )
    if category is None:
        raise HTTPException(404, "Category not found")
    await require_fresh_store_access(
        session,
        user_id=actor_id,
        store_id=category.store_id,
        capability="income_config.manage",
    )
    return category


@router.post("/income-categories/{category_id}/archive", response_model=IncomeCategoryResponse)
async def archive_income_category(
    category_id: int, session: Session, actor: IncomeConfigManager
) -> IncomeCategoryResponse:
    actor_id = actor.id
    async with sqlite_short_write(session):
        await _fresh_category_manager(
            session, actor_id=actor_id, category_id=category_id
        )
        category = await IncomeConfigService(session).archive(category_id)
        response = IncomeCategoryResponse.model_validate(category)
    return response


@router.post("/income-categories/{category_id}/restore", response_model=IncomeCategoryResponse)
async def restore_income_category(
    category_id: int, session: Session, actor: IncomeConfigManager
) -> IncomeCategoryResponse:
    actor_id = actor.id
    async with sqlite_short_write(session):
        await _fresh_category_manager(
            session, actor_id=actor_id, category_id=category_id
        )
        category = await IncomeConfigService(session).restore_category(
            category_id
        )
        response = IncomeCategoryResponse.model_validate(category)
    return response
