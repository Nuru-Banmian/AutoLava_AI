from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, Session
from app.core.config import get_settings
from app.core.security import create_access_token, verify_password
from app.models.identity import User
from app.schemas.auth import LoginBody
from app.services.access import list_accessible_stores

router = APIRouter(tags=["auth"])


@router.post("/auth/login")
async def login(body: LoginBody, response: Response, session: Session) -> dict:
    user = await session.scalar(select(User).where(User.username == body.username))
    if user is None or not user.is_active or not verify_password(body.password, user.password_hash):
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


@router.get("/auth/me")
async def me(user: CurrentUser) -> dict:
    return {"id": user.id, "username": user.username, "role": user.role}


@router.get("/stores/accessible")
async def accessible_stores(user: CurrentUser, session: Session) -> list[dict]:
    stores = await list_accessible_stores(session, user)
    return [{"id": store.id, "name": store.name, "timezone": store.timezone} for store in stores]
