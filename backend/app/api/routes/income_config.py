from fastapi import APIRouter, Depends

from app.api.deps import Session, require_admin
from app.core.database import SQLITE_WRITE_LOCK
from app.schemas.income_config import (
    IncomeCategoryResponse,
    IncomeConfigPublishBody,
    IncomeConfigResponse,
)
from app.services.income_config import IncomeConfigService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])


@router.get("/stores/{store_id}/income-config", response_model=IncomeConfigResponse)
async def get_income_config(store_id: int, session: Session) -> IncomeConfigResponse:
    service = IncomeConfigService(session)
    return await service.current(store_id)


@router.put("/stores/{store_id}/income-config", response_model=IncomeConfigResponse)
async def put_income_config(
    store_id: int,
    body: IncomeConfigPublishBody,
    session: Session,
) -> IncomeConfigResponse:
    async with SQLITE_WRITE_LOCK:
        try:
            await session.commit()
            service = IncomeConfigService(session)
            response = await service.replace(store_id, body)
            await session.commit()
            return response
        except Exception:
            await session.rollback()
            raise


@router.post("/income-categories/{category_id}/archive", response_model=IncomeCategoryResponse)
async def archive_income_category(
    category_id: int, session: Session
) -> IncomeCategoryResponse:
    async with SQLITE_WRITE_LOCK:
        try:
            await session.commit()
            category = await IncomeConfigService(session).archive(category_id)
            await session.commit()
            return IncomeCategoryResponse.model_validate(category)
        except Exception:
            await session.rollback()
            raise


@router.post("/income-categories/{category_id}/restore", response_model=IncomeCategoryResponse)
async def restore_income_category(
    category_id: int, session: Session
) -> IncomeCategoryResponse:
    async with SQLITE_WRITE_LOCK:
        try:
            await session.commit()
            category = await IncomeConfigService(session).restore_category(category_id)
            await session.commit()
            return IncomeCategoryResponse.model_validate(category)
        except Exception:
            await session.rollback()
            raise
