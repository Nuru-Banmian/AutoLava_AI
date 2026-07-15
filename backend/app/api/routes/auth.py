from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.core.config import get_settings
from app.core.security import create_access_token, hash_password, verify_password
from app.models.identity import User
from app.schemas.auth import LoginBody, PasswordChange
from app.services.access import list_accessible_stores

router = APIRouter(tags=["auth"])
_DUMMY_PASSWORD_HASH = "$2b$12$IQOOUtkNRsdb1U4AxGQsf.mE9yqB1P7aZxsi4Y3eqQ6kGfJkWVZl2"


@router.post("/auth/login")
async def login(body: LoginBody, response: Response, session: Session) -> dict:
    user = await session.scalar(select(User).where(User.username == body.username))
    password_hash = user.password_hash if user is not None else _DUMMY_PASSWORD_HASH
    password_matches = verify_password(body.password, password_hash)
    if user is None or not user.is_active or not password_matches:
        raise HTTPException(401, "Invalid credentials")
    token, max_age = create_access_token(user.id, body.remember)
    response.set_cookie(
        "access_token",
        token,
        httponly=True,
        secure=get_settings().cookie_secure,
        samesite="lax",
        max_age=max_age,
        path="/",
    )
    return {"id": user.id, "username": user.username, "role": user.role}


@router.post("/auth/logout", status_code=204)
async def logout(response: Response) -> None:
    response.delete_cookie("access_token", path="/")


@router.post("/auth/password", status_code=204)
async def change_password(body: PasswordChange, session: Session, user: CurrentUser) -> None:
    if not verify_password(body.current_password, user.password_hash):
        raise HTTPException(422, "当前密码不正确")
    user.password_hash = hash_password(body.new_password)
    await session.commit()


@router.get("/auth/me")
async def me(user: CurrentUser) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/stores/accessible")
async def accessible_stores(user: CurrentUser, session: Session) -> list[dict]:
    stores = await list_accessible_stores(session, user)
    return [{"id": store.id, "name": store.name, "timezone": store.timezone} for store in stores]
