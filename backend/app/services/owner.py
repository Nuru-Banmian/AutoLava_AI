from typing import Any

from app.core.config import get_settings
from app.models.identity import User


def owner_username() -> str:
    return get_settings().bootstrap_username.strip()


def is_owner(user: User) -> bool:
    configured = owner_username()
    return bool(configured) and user.username == configured


def authenticated_user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_owner": is_owner(user),
    }
