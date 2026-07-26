from typing import Any

from app.core.config import get_settings
from app.models.identity import User


def owner_username() -> str:
    return get_settings().bootstrap_username.strip()


def is_owner(user: User) -> bool:
    configured = owner_username()
    return bool(configured) and user.username == configured


def is_administrator(user: User) -> bool:
    return user.role == "admin" or is_owner(user)


def authenticated_user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": "admin" if is_administrator(user) else user.role,
        "is_owner": is_owner(user),
    }
