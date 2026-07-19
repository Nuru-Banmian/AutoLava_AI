import asyncio
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.orm import selectinload

from app.core.database import SQLITE_WRITE_LOCK, async_session_factory, engine
from app.core.security import hash_password
from app.main import create_app
from app.models.base import Base
from app.models.identity import Store, StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord


class PausedWeather:
    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.release = asyncio.Event()

    async def get_daily(self, store, target):
        self.entered.set()
        await self.release.wait()
        return None


async def _reset_database() -> None:
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())


async def _setup_ledger(*, role: str = "user", with_record: bool = False):
    async with async_session_factory() as session:
        user = User(
            username=f"ledger-{role}",
            password_hash=hash_password("secret"),
            role=role,
            is_active=True,
        )
        store = Store(
            name="Revocation",
            address="Revocation address",
            latitude=Decimal("45"),
            longitude=Decimal("9"),
            timezone="Europe/Berlin",
            is_active=True,
            income_items_enabled=True,
        )
        session.add_all([user, store])
        await session.flush()
        category = IncomeCategory(
            store_id=store.id,
            name="Cash",
            include_in_total=True,
            is_active=True,
            sort_order=0,
        )
        session.add_all(
            [category, StoreMember(store_id=store.id, user_id=user.id)]
        )
        await session.flush()
        target = datetime.now(ZoneInfo(store.timezone)).date()
        if with_record:
            session.add(
                StoreDailyRecord(
                    store_id=store.id,
                    date=target,
                    daily_revenue=100,
                    income_mode="composed",
                    is_open="营业",
                    created_by=user.id,
                    updated_by=user.id,
                    items=[
                        DailyIncomeItem(
                            category_id=category.id,
                            category_name=category.name,
                            include_in_total=True,
                            sort_order=0,
                            amount=100,
                        )
                    ],
                )
            )
        await session.commit()
        return user.id, store.id, category.id, target


async def _logged_in_client(username: str) -> AsyncClient:
    app = create_app()
    client = AsyncClient(
        transport=ASGITransport(app=app), base_url="http://testserver"
    )
    response = await client.post(
        "/api/auth/login", json={"username": username, "password": "secret"}
    )
    assert response.status_code == 200
    return client


def _payload(category_id: int, amount: int) -> dict:
    return {
        "is_open": "营业",
        "daily_revenue": None,
        "items": [{"category_id": category_id, "amount": amount}],
    }


async def test_create_rejects_actor_deactivated_during_weather() -> None:
    await _reset_database()
    user_id, store_id, category_id, target = await _setup_ledger()
    client = await _logged_in_client("ledger-user")
    weather = PausedWeather()
    client._transport.app.state.weather_service = weather
    request = asyncio.create_task(
        client.put(
            f"/api/ledger/{store_id}/{target.isoformat()}",
            json=_payload(category_id, 125),
        )
    )
    await weather.entered.wait()
    async with async_session_factory() as revoke:
        user = await revoke.get(User, user_id)
        assert user is not None
        user.is_active = False
        await revoke.commit()
    weather.release.set()
    response = await request
    await client.aclose()

    assert response.status_code == 401
    async with async_session_factory() as verify:
        assert await verify.scalar(
            select(func.count()).select_from(StoreDailyRecord)
        ) == 0


async def test_update_rejects_membership_removed_during_weather() -> None:
    await _reset_database()
    user_id, store_id, category_id, target = await _setup_ledger(with_record=True)
    client = await _logged_in_client("ledger-user")
    weather = PausedWeather()
    client._transport.app.state.weather_service = weather
    request = asyncio.create_task(
        client.put(
            f"/api/ledger/{store_id}/{target.isoformat()}",
            json=_payload(category_id, 250),
        )
    )
    await weather.entered.wait()
    async with async_session_factory() as revoke:
        await revoke.execute(
            delete(StoreMember).where(
                StoreMember.store_id == store_id,
                StoreMember.user_id == user_id,
            )
        )
        await revoke.commit()
    weather.release.set()
    response = await request
    await client.aclose()

    assert response.status_code == 403
    async with async_session_factory() as verify:
        assert await verify.scalar(
            select(StoreDailyRecord.daily_revenue).where(
                StoreDailyRecord.store_id == store_id,
                StoreDailyRecord.date == target,
            )
        ) == 100


async def test_delete_rejects_store_archived_while_waiting_for_lock() -> None:
    await _reset_database()
    _, store_id, _, target = await _setup_ledger(
        role="admin", with_record=True
    )
    client = await _logged_in_client("ledger-admin")
    await SQLITE_WRITE_LOCK.acquire()
    try:
        request = asyncio.create_task(
            client.delete(f"/api/ledger/{store_id}/{target.isoformat()}")
        )
        while not SQLITE_WRITE_LOCK._waiters:
            await asyncio.sleep(0)
        async with async_session_factory() as archive:
            store = await archive.get(Store, store_id)
            assert store is not None
            store.is_active = False
            await archive.commit()
    finally:
        SQLITE_WRITE_LOCK.release()
    response = await request
    await client.aclose()

    assert response.status_code == 404
    async with async_session_factory() as verify:
        assert await verify.scalar(
            select(func.count())
            .select_from(StoreDailyRecord)
            .where(StoreDailyRecord.store_id == store_id)
        ) == 1


async def test_create_uses_config_committed_during_weather_wait() -> None:
    await _reset_database()
    _, store_id, category_id, target = await _setup_ledger()
    async with async_session_factory() as setup:
        store = await setup.get(Store, store_id)
        assert store is not None
        store.income_items_enabled = False
        await setup.commit()

    client = await _logged_in_client("ledger-user")
    weather = PausedWeather()
    client._transport.app.state.weather_service = weather
    request = asyncio.create_task(
        client.put(
            f"/api/ledger/{store_id}/{target.isoformat()}",
            json=_payload(category_id, 125),
        )
    )
    await weather.entered.wait()
    async with async_session_factory() as configure:
        store = await configure.get(Store, store_id)
        category = await configure.get(IncomeCategory, category_id)
        assert store is not None
        assert category is not None
        store.income_items_enabled = True
        category.name = "Latest cash"
        category.include_in_total = False
        category.sort_order = 7
        await configure.commit()
    weather.release.set()
    response = await request
    await client.aclose()

    assert response.status_code == 201
    async with async_session_factory() as verify:
        record = await verify.scalar(
            select(StoreDailyRecord)
            .where(
                StoreDailyRecord.store_id == store_id,
                StoreDailyRecord.date == target,
            )
            .options(selectinload(StoreDailyRecord.items))
        )
        assert record is not None
        assert record.income_mode == "composed"
        assert record.daily_revenue == 0
        assert [
            (
                item.category_name,
                item.include_in_total,
                item.sort_order,
                item.amount,
            )
            for item in record.items
        ] == [("Latest cash", False, 7, 125)]
