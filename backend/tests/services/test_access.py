import pytest
from fastapi import HTTPException

from app.api.deps import require_capability
from app.models.identity import User
from app.services.access import ROLE_CAPABILITIES, has_capability


def make_user(*, role: str) -> User:
    return User(
        username=f"{role}-user",
        password_hash="not-used",
        role=role,
        is_active=True,
    )


def test_role_capabilities_preserve_current_role_permissions() -> None:
    assert ROLE_CAPABILITIES["user"] == frozenset(
        {
            "ledger.view",
            "ledger.create",
            "ledger.edit",
            "analytics.view",
        }
    )
    assert ROLE_CAPABILITIES["admin"] == frozenset(
        {
            "ledger.view",
            "ledger.create",
            "ledger.edit",
            "ledger.delete",
            "analytics.view",
            "income_config.manage",
            "users.manage",
            "stores.manage",
            "audit.view",
        }
    )


def test_capability_check_is_independent_of_store_membership() -> None:
    user = make_user(role="user")

    assert has_capability(user, "ledger.create") is True
    assert has_capability(user, "ledger.delete") is False


def test_regular_user_cannot_delete_or_view_audit_history() -> None:
    user = make_user(role="user")

    assert has_capability(user, "ledger.delete") is False
    assert has_capability(user, "audit.view") is False
    assert has_capability(user, "ledger.edit") is True


def test_unknown_role_has_no_capabilities() -> None:
    assert has_capability(make_user(role="future-role"), "ledger.view") is False


async def test_capability_dependency_returns_authorized_user() -> None:
    user = make_user(role="user")

    dependency = require_capability("ledger.edit")

    assert await dependency(user) is user


async def test_capability_dependency_rejects_unauthorized_user() -> None:
    dependency = require_capability("users.manage")

    with pytest.raises(HTTPException) as exc_info:
        await dependency(make_user(role="user"))

    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Insufficient permissions"
