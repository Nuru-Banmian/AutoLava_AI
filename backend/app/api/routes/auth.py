from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.core.config import get_settings
from app.core.database import sqlite_short_write
from app.core.security import create_access_token, hash_password, verify_password
from app.models.identity import User
from app.models.identity import LoginSession
from app.schemas.auth import LoginBody, PasswordChange
from app.services.access import list_accessible_stores, require_fresh_user
from app.services.owner import authenticated_user_payload
from app.services.sessions import current_credentials, new_session, require_credentials, revoke_all, utc_now

router = APIRouter(tags=["auth"])
_DUMMY_PASSWORD_HASH = "$2b$12$IQOOUtkNRsdb1U4AxGQsf.mE9yqB1P7aZxsi4Y3eqQ6kGfJkWVZl2"


def _set_auth_cookie(response: Response, auth_identity: str, session_id: str) -> None:
    token, max_age = create_access_token(auth_identity, session_id)
    response.set_cookie(
        "access_token", token, httponly=True, secure=get_settings().cookie_secure,
        samesite="lax", max_age=max_age, path="/",
    )


@router.post("/auth/login")
async def login(body: LoginBody, response: Response, session: Session) -> dict:
    user = await session.scalar(select(User).where(User.username == body.username))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(body.password, password_hash)
    if user is None or not user.is_active or not password_matches:
        raise HTTPException(401, "Invalid credentials")
    identity, verified_hash = user.auth_identity, user.password_hash
    # Release the password snapshot before waiting for the write lock.
    await session.commit()
    async with sqlite_short_write(session):
        fresh_user = await session.scalar(
            select(User).where(User.auth_identity == identity).execution_options(populate_existing=True)
        )
        if fresh_user is None or not fresh_user.is_active or fresh_user.password_hash != verified_hash:
            raise HTTPException(401, "Invalid credentials")
        login_session = await new_session(session, fresh_user)
        payload = authenticated_user_payload(fresh_user)
    _set_auth_cookie(response, identity, login_session.id)
    return payload


@router.post("/auth/logout", status_code=204)
async def logout(response: Response, session: Session, user: CurrentUser) -> None:
    credentials = current_credentials.get()
    assert credentials is not None
    async with sqlite_short_write(session):
        await require_credentials(session, *credentials)
        login_session = await session.get(LoginSession, credentials[1], populate_existing=True)
        assert login_session is not None
        login_session.revoked_at = utc_now()
    response.delete_cookie("access_token", path="/")


@router.post("/auth/password", status_code=204)
async def change_password(
    body: PasswordChange, response: Response, session: Session, user: CurrentUser
) -> None:
    actor_id = user.id
    credentials = current_credentials.get()
    assert credentials is not None
    next_password_hash = hash_password(body.new_password)
    async with sqlite_short_write(session):
        locked_user = await require_fresh_user(session, user_id=actor_id)
        if not verify_password(body.current_password, locked_user.password_hash):
            raise HTTPException(422, "当前密码不正确")
        locked_user.password_hash = next_password_hash
        await revoke_all(session, locked_user.auth_identity)
        replacement = await new_session(session, locked_user)
    _set_auth_cookie(response, locked_user.auth_identity, replacement.id)


@router.get("/auth/me")
async def me(user: CurrentUser) -> dict:
    return authenticated_user_payload(user)


@router.get("/stores/accessible")
async def accessible_stores(user: CurrentUser, session: Session) -> list[dict]:
    stores = await list_accessible_stores(session, user)
    return [
        {
            "id": store.id,
            "name": store.name,
            "timezone": store.timezone,
            "is_active": store.is_active,
            "company_settlement_enabled": store.company_settlement_enabled,
            "wash_count_enabled": store.wash_count_enabled,
        }
        for store in stores
    ]
