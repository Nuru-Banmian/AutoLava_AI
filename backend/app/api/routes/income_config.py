from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Session, require_admin
from app.models.identity import User
from app.schemas.income_config import (
    IncomeCategoryResponse,
    IncomeConfigPublishBody,
    IncomeConfigResponse,
)
from app.services.income_config import IncomeConfigService

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
AdminUser = Annotated[User, Depends(require_admin)]


@router.get("/stores/{store_id}/income-config", response_model=IncomeConfigResponse)
async def get_income_config(store_id: int, session: Session) -> IncomeConfigResponse:
    service = IncomeConfigService(session)
    return service.response(await service.current(store_id), store_id=store_id)


@router.put("/stores/{store_id}/income-config", response_model=IncomeConfigResponse)
async def put_income_config(
    store_id: int,
    body: IncomeConfigPublishBody,
    session: Session,
    actor: AdminUser,
) -> IncomeConfigResponse:
    service = IncomeConfigService(session)
    version = await service.publish(store_id, body, actor)
    await session.commit()
    return service.response(version, store_id=store_id)


@router.get("/stores/{store_id}/income-config/versions", response_model=list[IncomeConfigResponse])
async def list_income_config_versions(
    store_id: int, session: Session
) -> list[IncomeConfigResponse]:
    service = IncomeConfigService(session)
    return [
        service.response(version, store_id=store_id)
        for version in await service.versions(store_id)
    ]


@router.post(
    "/stores/{store_id}/income-config/versions/{version_id}/restore",
    response_model=IncomeConfigResponse,
)
async def restore_income_config(
    store_id: int, version_id: int, session: Session, actor: AdminUser
) -> IncomeConfigResponse:
    service = IncomeConfigService(session)
    version = await service.restore(store_id, version_id, actor)
    await session.commit()
    return service.response(version, store_id=store_id)


@router.post("/income-categories/{category_id}/archive", response_model=IncomeCategoryResponse)
async def archive_income_category(
    category_id: int, session: Session, actor: AdminUser
) -> IncomeCategoryResponse:
    category = await IncomeConfigService(session).archive(category_id, actor)
    await session.commit()
    return IncomeCategoryResponse.model_validate(category)


@router.post("/income-categories/{category_id}/restore", response_model=IncomeCategoryResponse)
async def restore_income_category(
    category_id: int, session: Session, actor: AdminUser
) -> IncomeCategoryResponse:
    category = await IncomeConfigService(session).restore_category(category_id, actor)
    await session.commit()
    return IncomeCategoryResponse.model_validate(category)
