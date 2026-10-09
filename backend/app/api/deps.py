from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, Request
from jwt import InvalidTokenError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.security import decode_access_token
from app.models.identity import Store, User
from app.services.access import Capability, has_capability, require_store_scope
from app.services.owner import is_administrator, is_owner
from app.services.sessions import current_credentials, request_auth_required, require_credentials


async def request_session(
    request: Request, session: Annotated[AsyncSession, Depends(get_session)]
) -> AsyncIterator[AsyncSession]:
    """Mark public HTTP calls so write revalidation cannot use an ID-only fallback."""
    token = request_auth_required.set(True)
    try:
        yield session
    finally:
        request_auth_required.reset(token)


Session = Annotated[AsyncSession, Depends(request_session)]


async def get_current_user(
    session: Session, access_token: str | None = Cookie(None)
) -> AsyncIterator[User]:
    try:
        auth_identity, session_id = decode_access_token(access_token or "")
    except InvalidTokenError as exc:
        raise HTTPException(401, "Authentication required") from exc
    user = await require_credentials(session, auth_identity, session_id)
    token = current_credentials.set((auth_identity, session_id))
    try:
        yield user
    finally:
        current_credentials.reset(token)


CurrentUser = Annotated[User, Depends(get_current_user)]


async def require_admin(user: CurrentUser) -> User:
    if not is_administrator(user):
        raise HTTPException(403, "Administrator access required")
    return user


async def require_final_admin(user: CurrentUser) -> User:
    if not is_owner(user):
        raise HTTPException(403, "Final administrator access required")
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
    await require_store_scope(session, user, store_id)
    return StoreAccess(store=store, user=user)


async def require_store_read_access(
    store_id: int, user: CurrentUser, session: Session
) -> StoreAccess:
    store = await session.get(Store, store_id)
    if store is None or (not store.is_active and not is_administrator(user)):
        raise HTTPException(404, "Store not found")
    await require_store_scope(session, user, store_id)
    return StoreAccess(store=store, user=user)
