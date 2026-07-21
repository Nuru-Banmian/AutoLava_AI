from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, Session
from app.models.identity import Store, User
from app.services.access import require_company_settlement_access


router = APIRouter(prefix="/settlements", tags=["company-settlement"])


async def require_enabled_settlement_store(
    store_id: int,
    user: CurrentUser,
    session: Session,
) -> tuple[User, Store]:
    return await require_company_settlement_access(
        session, user_id=user.id, store_id=store_id
    )


EnabledSettlementStore = Annotated[
    tuple[User, Store], Depends(require_enabled_settlement_store)
]


@router.get("/{store_id}")
async def settlement_workspace(
    store_id: int,
    access: EnabledSettlementStore,
) -> dict[str, int | str | bool]:
    """Return the gated shell used by later settlement vertical slices."""
    _, store = access
    return {
        "store_id": store.id,
        "store_name": store.name,
        "company_settlement_enabled": True,
    }
