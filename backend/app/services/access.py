from typing import Literal, get_args

from fastapi import HTTPException
from sqlalchemy import select, exists, false
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, StoreMember, User
from app.services.owner import is_administrator, is_owner
from app.services.sessions import current_credentials, request_auth_required, require_credentials


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
    role = "admin" if is_administrator(user) else user.role
    return capability in ROLE_CAPABILITIES.get(role, frozenset())


async def require_fresh_user(
    session: AsyncSession,
    *,
    user_id: int,
    capability: Capability | None = None,
) -> User:
    credentials = current_credentials.get()
    if request_auth_required.get() and credentials is None:
        raise HTTPException(401, "Authentication required")
    if credentials is not None:
        user = await require_credentials(session, *credentials)
        if user.id != user_id:
            raise HTTPException(401, "Authentication required")
    else:
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
    user = await require_fresh_user(session, user_id=user_id, capability=capability)
    store = await session.get(Store, store_id, populate_existing=True)
    if store is None or not store.is_active:
        raise HTTPException(404, "Store not found")
    await require_store_scope(session, user, store_id)
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


async def store_scope_clause(session: AsyncSession, user: User):
    """One authority for business, management and background store access."""
    if is_owner(user):
        from sqlalchemy import true

        return true()
    own = (
        exists()
        .where(StoreMember.store_id == Store.id, StoreMember.user_id == user.id)
        .correlate(Store)
    )
    if is_administrator(user):
        return own
    manager = (
        await session.get(User, user.manager_id, populate_existing=True)
        if user.manager_id is not None
        else None
    )
    if manager is None or not is_administrator(manager):
        return false()
    if is_owner(manager):
        return own
    return own & exists().where(
        StoreMember.store_id == Store.id, StoreMember.user_id == manager.id
    ).correlate(Store)


async def require_store_scope(session: AsyncSession, user: User, store_id: int) -> None:
    allowed = await session.scalar(
        select(Store.id).where(Store.id == store_id, await store_scope_clause(session, user))
    )
    if allowed is None:
        raise HTTPException(404, "Store not found")


async def list_accessible_stores(session: AsyncSession, user: User) -> list[Store]:
    query = select(Store).order_by(Store.name)
    query = query.where(await store_scope_clause(session, user))
    if not is_administrator(user):
        query = query.where(Store.is_active.is_(True))
    return list((await session.scalars(query)).all())
