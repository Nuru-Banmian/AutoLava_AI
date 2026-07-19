from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import Session, StoreAccess, require_store_read_access
from app.schemas.income_config import IncomeConfigResponse
from app.services.income_config import IncomeConfigService

router = APIRouter(prefix="/income-config", tags=["income-config"])


@router.get("/{store_id}/current", response_model=IncomeConfigResponse)
async def get_current_income_config(
    session: Session,
    access: Annotated[StoreAccess, Depends(require_store_read_access)],
) -> IncomeConfigResponse:
    service = IncomeConfigService(session)
    return await service.current(access.store.id)
