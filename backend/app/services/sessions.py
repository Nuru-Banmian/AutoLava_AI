"""Persisted authentication sessions and request bound write revalidation."""

from contextvars import ContextVar
from datetime import UTC, datetime, timedelta
from secrets import token_hex

from fastapi import HTTPException
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import ACCESS_TOKEN_SECONDS
from app.models.identity import LoginSession, User

RequestCredentials = tuple[str, str]
current_credentials: ContextVar[RequestCredentials | None] = ContextVar(
    "current_credentials", default=None
)
request_auth_required: ContextVar[bool] = ContextVar("request_auth_required", default=False)


def utc_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def new_session(session: AsyncSession, user: User) -> LoginSession:
    login_session = LoginSession(
        id=token_hex(32),
        auth_identity=user.auth_identity,
        expires_at=utc_now() + timedelta(seconds=ACCESS_TOKEN_SECONDS),
    )
    session.add(login_session)
    await session.flush()
    return login_session


async def revoke_all(session: AsyncSession, auth_identity: str) -> None:
    await session.execute(
        update(LoginSession)
        .where(LoginSession.auth_identity == auth_identity, LoginSession.revoked_at.is_(None))
        .values(revoked_at=utc_now())
    )


async def require_credentials(
    session: AsyncSession, auth_identity: str, session_id: str
) -> User:
    login_session = await session.get(LoginSession, session_id, populate_existing=True)
    if (
        login_session is None
        or login_session.auth_identity != auth_identity
        or login_session.revoked_at is not None
        or login_session.expires_at <= utc_now()
    ):
        raise HTTPException(401, "Authentication required")
    from sqlalchemy import select

    user = await session.scalar(
        select(User).where(User.auth_identity == auth_identity).execution_options(populate_existing=True)
    )
    if user is None or not user.is_active:
        raise HTTPException(401, "Authentication required")
    return user
