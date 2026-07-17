from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException
from jwt import InvalidTokenError
from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.identity import Store, StoreMember, User
from app.services.access import Capability, has_capability

Session = Annotated[AsyncSession, Depends(get_session)]


async def get_current_user(session: Session, access_token: str | None = Cookie(None)) -> User:
    try:
        user_id = decode_access_token(access_token or "")
    except InvalidTokenError as exc:
        raise HTTPException(401, "Authentication required") from exc
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, "Authentication required")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if user.role != "admin":
        raise HTTPException(403, "Administrator access required")
    return user


def require_capability(capability: Capability) -> Callable[[User], Awaitable[User]]:
    async def dependency(user: CurrentUser) -> User:
        if not has_capability(user, capability):
            raise HTTPException(403, "Insufficient permissions")
        return user

    return dependency


@dataclass(frozen=True)
class StoreAccess:
    store: Store
    user: User


async def require_store_access(store_id: int, user: CurrentUser, session: Session) -> StoreAccess:
    store = await session.get(Store, store_id)
    if store is None or not store.is_active:
        raise HTTPException(404, "Store not found")
    allowed = user.role == "admin" or await session.scalar(
        select(exists().where(StoreMember.store_id == store_id, StoreMember.user_id == user.id))
    )
    if not allowed:
        raise HTTPException(404, "Store not found")
    return StoreAccess(store=store, user=user)


async def require_store_read_access(
    store_id: int, user: CurrentUser, session: Session
) -> StoreAccess:
    store = await session.get(Store, store_id)
    if store is None or (not store.is_active and user.role != "admin"):
        raise HTTPException(404, "Store not found")
    allowed = user.role == "admin" or await session.scalar(
        select(exists().where(StoreMember.store_id == store_id, StoreMember.user_id == user.id))
    )
    if not allowed:
        raise HTTPException(404, "Store not found")
    return StoreAccess(store=store, user=user)
