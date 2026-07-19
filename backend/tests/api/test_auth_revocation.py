import asyncio

from httpx import ASGITransport, AsyncClient

from app.core.database import SQLITE_WRITE_LOCK, async_session_factory, engine
from app.core.security import hash_password, verify_password
from app.main import create_app
from app.models.base import Base
from app.models.identity import User


async def _reset_database() -> None:
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())


async def test_password_change_rejects_user_deactivated_while_waiting_for_lock() -> None:
    await _reset_database()
    async with async_session_factory() as setup:
        user = User(
            username="password-revoked",
            password_hash=hash_password("OldPassword1"),
            role="user",
            is_active=True,
        )
        setup.add(user)
        await setup.commit()
        user_id = user.id

    app = create_app()
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login = await client.post(
            "/api/auth/login",
            json={"username": "password-revoked", "password": "OldPassword1"},
        )
        assert login.status_code == 200

        await SQLITE_WRITE_LOCK.acquire()
        try:
            mutation = asyncio.create_task(
                client.post(
                    "/api/auth/password",
                    json={
                        "current_password": "OldPassword1",
                        "new_password": "NewPassword2",
                    },
                )
            )
            while not SQLITE_WRITE_LOCK._waiters and not mutation.done():
                await asyncio.sleep(0)
            assert not mutation.done()

            async with async_session_factory() as revoke:
                current = await revoke.get(User, user_id)
                assert current is not None
                current.is_active = False
                await revoke.commit()
        finally:
            SQLITE_WRITE_LOCK.release()

        response = await mutation

    assert response.status_code == 401
    async with async_session_factory() as verify:
        current = await verify.get(User, user_id)
        assert current is not None
        assert verify_password("OldPassword1", current.password_hash)
        assert not verify_password("NewPassword2", current.password_hash)
