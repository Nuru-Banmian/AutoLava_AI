import asyncio

import pytest
from sqlalchemy import delete, func, select

from app.core.database import async_session_factory, engine
from app.core.security import verify_password
from app.models.identity import User


async def test_create_admin_inserts_no_token_field_and_is_idempotent(db_session) -> None:
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


async def test_create_admin_accepts_128_character_password_and_can_log_in(
    db_session, client
) -> None:
    from app.scripts.create_admin import create_admin

    password = "p" * 128
    assert await create_admin(db_session, "long-password-admin", password) is True

    response = await client.post(
        "/api/auth/login",
        json={"username": "long-password-admin", "password": password},
    )
    assert response.status_code == 200


async def test_simultaneous_create_admin_attempts_are_atomic() -> None:
    from app.scripts.create_admin import create_admin

    username = "concurrent-bootstrap-admin"
    async with engine.begin() as connection:
        await connection.execute(delete(User).where(User.username == username))

    async def attempt() -> bool:
        async with async_session_factory() as session:
            async with session.begin():
                return await create_admin(session, username, "concurrent-password")

    try:
        results = await asyncio.gather(attempt(), attempt(), return_exceptions=True)
        assert all(isinstance(result, bool) for result in results), results
        assert results.count(True) == 1
        assert results.count(False) == 1
        async with async_session_factory() as session:
            count = await session.scalar(
                select(func.count()).select_from(User).where(User.username == username)
            )
        assert count == 1
    finally:
        async with engine.begin() as connection:
            await connection.execute(delete(User).where(User.username == username))


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


@pytest.mark.parametrize("length", [3, 80])
def test_bootstrap_credentials_accept_username_boundaries(length: int) -> None:
    from app.scripts.create_admin import credentials_from_environment

    username = "u" * length
    assert credentials_from_environment(
        {
            "AUTOLAVA_BOOTSTRAP_USERNAME": username,
            "AUTOLAVA_BOOTSTRAP_PASSWORD": "password",
        }
    ) == (username, "password")


@pytest.mark.parametrize("length", [8, 128])
def test_bootstrap_credentials_accept_password_boundaries(length: int) -> None:
    from app.scripts.create_admin import credentials_from_environment

    password = "p" * length
    assert credentials_from_environment(
        {
            "AUTOLAVA_BOOTSTRAP_USERNAME": "admin",
            "AUTOLAVA_BOOTSTRAP_PASSWORD": password,
        }
    ) == ("admin", password)


@pytest.mark.parametrize(
    ("username", "password", "field"),
    [
        ("uu", "password", "AUTOLAVA_BOOTSTRAP_USERNAME"),
        ("u" * 81, "password", "AUTOLAVA_BOOTSTRAP_USERNAME"),
        ("admin", " " * 8, "AUTOLAVA_BOOTSTRAP_PASSWORD"),
        ("admin", "p" * 7, "AUTOLAVA_BOOTSTRAP_PASSWORD"),
        ("admin", "p" * 129, "AUTOLAVA_BOOTSTRAP_PASSWORD"),
    ],
)
def test_bootstrap_credentials_reject_invalid_user_create_boundaries(
    username: str, password: str, field: str
) -> None:
    from app.scripts.create_admin import credentials_from_environment

    with pytest.raises(RuntimeError, match=field) as caught:
        credentials_from_environment(
            {
                "AUTOLAVA_BOOTSTRAP_USERNAME": username,
                "AUTOLAVA_BOOTSTRAP_PASSWORD": password,
            }
        )
    assert username not in str(caught.value)
    assert password not in str(caught.value)
