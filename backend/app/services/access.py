from typing import Literal, get_args

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, StoreMember, User


Capability = Literal[
    "ledger.view",
    "ledger.create",
    "ledger.edit",
    "ledger.delete",
    "analytics.view",
    "income_config.manage",
    "users.manage",
    "stores.manage",
]

ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    "user": frozenset(
        {
            "ledger.view",
            "ledger.create",
            "ledger.edit",
            "analytics.view",
        }
    ),
    "admin": frozenset(get_args(Capability)),
}


def has_capability(user: User, capability: Capability) -> bool:
    return capability in ROLE_CAPABILITIES.get(user.role, frozenset())


async def require_fresh_user(
    session: AsyncSession,
    *,
    user_id: int,
    capability: Capability | None = None,
) -> User:
    user = await session.get(User, user_id, populate_existing=True)
    if user is None or not user.is_active:
        raise HTTPException(401, "Authentication required")
    if capability is not None and not has_capability(user, capability):
        raise HTTPException(403, "Insufficient permissions")
    return user


async def require_fresh_store_access(
    session: AsyncSession,
    *,
    user_id: int,
    store_id: int,
    capability: Capability,
) -> tuple[User, Store]:
    user = await require_fresh_user(
        session, user_id=user_id, capability=capability
    )
    store = await session.get(Store, store_id, populate_existing=True)
    if store is None or not store.is_active:
        raise HTTPException(404, "Store not found")
    if user.role != "admin":
        membership = await session.scalar(
            select(StoreMember.id).where(
                StoreMember.store_id == store_id,
                StoreMember.user_id == user_id,
            )
        )
        if membership is None:
            raise HTTPException(403, "Store membership required")
    return user, store


async def require_company_settlement_access(
    session: AsyncSession,
    *,
    user_id: int,
    store_id: int,
) -> tuple[User, Store]:
    """Require live store access and the server-owned settlement capability."""
    user, store = await require_fresh_store_access(
        session,
        user_id=user_id,
        store_id=store_id,
        capability="ledger.view",
    )
    if not store.company_settlement_enabled:
        raise HTTPException(403, "当前门店未启用公司结算")
    return user, store


async def list_accessible_stores(session: AsyncSession, user: User) -> list[Store]:
    query = select(Store).order_by(Store.name)
    if user.role != "admin":
        query = query.where(Store.is_active.is_(True)).join(StoreMember).where(
            StoreMember.user_id == user.id
        )
    return list((await session.scalars(query)).all())
