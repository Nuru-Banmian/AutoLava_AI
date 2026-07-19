import asyncio
from decimal import Decimal

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select

from app.core.database import async_session_factory, engine
from app.core.security import hash_password
from app.main import create_app
from app.models.base import Base
from app.models.identity import Store, StoreMember, User
from app.models.operations import DailyBriefing


class PausedWeather:
    def __init__(self) -> None:
        self.calls = 0
        self.all_entered = asyncio.Event()
        self.release = asyncio.Event()

    async def get_daily(self, store, target):
        self.calls += 1
        if self.calls == 2:
            self.all_entered.set()
        await self.release.wait()
        return None


async def _reset_database() -> None:
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())


async def _setup_dashboard() -> tuple[int, int]:
    async with async_session_factory() as setup:
        user = User(
            username="dashboard-revoked",
            password_hash=hash_password("secret"),
            role="user",
            is_active=True,
        )
        store = Store(
            name="Dashboard revocation",
            address="Dashboard revocation address",
            latitude=Decimal("45"),
            longitude=Decimal("9"),
            timezone="Europe/Berlin",
            is_active=True,
        )
        setup.add_all([user, store])
        await setup.flush()
        setup.add(StoreMember(store_id=store.id, user_id=user.id))
        await setup.commit()
        return user.id, store.id


async def test_refresh_rejects_user_deactivated_during_weather() -> None:
    await _reset_database()
    user_id, store_id = await _setup_dashboard()
    app = create_app()
    weather = PausedWeather()
    app.state.weather_service = weather

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login = await client.post(
            "/api/auth/login",
            json={"username": "dashboard-revoked", "password": "secret"},
        )
        assert login.status_code == 200

        refresh = asyncio.create_task(
            client.post(f"/api/dashboard/{store_id}/refresh")
        )
        await weather.all_entered.wait()
        async with async_session_factory() as revoke:
            user = await revoke.get(User, user_id)
            assert user is not None
            user.is_active = False
            await revoke.commit()
        weather.release.set()
        response = await refresh

    assert response.status_code == 401
    async with async_session_factory() as verify:
        assert await verify.scalar(
            select(func.count()).select_from(DailyBriefing)
        ) == 0


async def test_refresh_rejects_membership_removed_during_weather() -> None:
    await _reset_database()
    user_id, store_id = await _setup_dashboard()
    app = create_app()
    weather = PausedWeather()
    app.state.weather_service = weather

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    ) as client:
        login = await client.post(
            "/api/auth/login",
            json={"username": "dashboard-revoked", "password": "secret"},
        )
        assert login.status_code == 200

        refresh = asyncio.create_task(
            client.post(f"/api/dashboard/{store_id}/refresh")
        )
        await weather.all_entered.wait()
        async with async_session_factory() as revoke:
            await revoke.execute(
                delete(StoreMember).where(
                    StoreMember.store_id == store_id,
                    StoreMember.user_id == user_id,
                )
            )
            await revoke.commit()
        weather.release.set()
        response = await refresh

    assert response.status_code == 403
    async with async_session_factory() as verify:
        assert await verify.scalar(
            select(func.count()).select_from(DailyBriefing)
        ) == 0
