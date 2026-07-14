import pytest
from sqlalchemy import func, select

from app.core.security import verify_password
from app.models.identity import User


async def test_create_admin_hashes_password_and_is_idempotent(db_session) -> None:
    from app.scripts.create_admin import create_admin

    assert await create_admin(db_session, "first-admin", "initial-password") is True
    first = await db_session.scalar(select(User).where(User.username == "first-admin"))
    assert first is not None
    first_hash = first.password_hash
    assert first.role == "admin"
    assert first.is_active is True
    assert verify_password("initial-password", first_hash)

    assert await create_admin(db_session, "first-admin", "replacement-password") is False
    assert await db_session.scalar(select(func.count()).select_from(User)) == 1
    await db_session.refresh(first)
    assert first.password_hash == first_hash
    assert verify_password("replacement-password", first.password_hash) is False


async def test_create_admin_does_not_change_an_existing_account(db_session, user_factory) -> None:
    from app.scripts.create_admin import create_admin

    existing = await user_factory(
        username="existing", password="worker-password", role="user", is_active=False
    )
    original_hash = existing.password_hash

    assert await create_admin(db_session, "existing", "admin-password") is False
    await db_session.refresh(existing)
    assert (existing.role, existing.is_active, existing.password_hash) == (
        "user",
        False,
        original_hash,
    )


def test_bootstrap_credentials_require_both_nonempty_environment_values() -> None:
    from app.scripts.create_admin import credentials_from_environment

    assert credentials_from_environment(
        {
            "AUTOLAVA_BOOTSTRAP_USERNAME": "first-admin",
            "AUTOLAVA_BOOTSTRAP_PASSWORD": "strong-password",
        }
    ) == ("first-admin", "strong-password")
    with pytest.raises(RuntimeError, match="AUTOLAVA_BOOTSTRAP_USERNAME"):
        credentials_from_environment({"AUTOLAVA_BOOTSTRAP_PASSWORD": "strong-password"})
    with pytest.raises(RuntimeError, match="AUTOLAVA_BOOTSTRAP_PASSWORD"):
        credentials_from_environment({"AUTOLAVA_BOOTSTRAP_USERNAME": "first-admin"})
