import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import SQLITE_WRITE_LOCK, async_session_factory, engine
from app.models.base import Base
from app.models.identity import Store, User
from app.models.ledger import IncomeCategory, StoreDailyRecord
from app.schemas.income_config import IncomeConfigPublishBody
from app.services.income_config import IncomeConfigService
from app.services.ledger import LedgerService


@dataclass
class LedgerContext:
    session: AsyncSession
    user: User
    store: Store
    cash: IncomeCategory
    agency: IncomeCategory
    user_id: int
    store_id: int
    cash_id: int
    agency_id: int
    timezone: str

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self.timezone)).date()


@pytest.fixture
async def ledger_context(db_session, user_factory, store_factory) -> LedgerContext:
    user = await user_factory(
        username="ledger-user", password="secret", role="admin"
    )
    store = await store_factory(name="Ledger Store", timezone="Europe/Berlin")
    store.income_items_enabled = True
    cash = IncomeCategory(
        store_id=store.id,
        name="Cash",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    agency = IncomeCategory(
        store_id=store.id,
        name="Agency",
        include_in_total=False,
        is_active=True,
        sort_order=1,
    )
    db_session.add_all([cash, agency])
    await db_session.commit()
    return LedgerContext(
        db_session,
        user,
        store,
        cash,
        agency,
        user_id=user.id,
        store_id=store.id,
        cash_id=cash.id,
        agency_id=agency.id,
        timezone=store.timezone,
    )


def composed_payload(context: LedgerContext, *, cash: int = 100, agency: int = 50) -> dict:
    return {
        "is_open": "营业",
        "daily_revenue": None,
        "wash_count": 3,
        "weather": "晴",
        "weather_edited": False,
        "activity": None,
        "items": [
            {"category_id": context.cash_id, "amount": cash},
            {"category_id": context.agency_id, "amount": agency},
        ],
    }


async def test_composed_total_sums_only_included_integer_items(
    ledger_context: LedgerContext,
) -> None:
    result = await LedgerService(ledger_context.session).upsert(
        store_id=ledger_context.store_id,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context),
        actor_id=ledger_context.user_id,
    )
    assert result.record.daily_revenue == 100
    assert [item.amount for item in result.record.items] == [100, 50]


async def test_second_write_directly_overwrites_existing_record(
    ledger_context: LedgerContext,
) -> None:
    service = LedgerService(ledger_context.session)
    first = await service.upsert(
        store_id=ledger_context.store_id,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context),
        actor_id=ledger_context.user_id,
    )
    second = await service.upsert(
        store_id=ledger_context.store_id,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context, cash=175),
        actor_id=ledger_context.user_id,
    )
    assert second.created is False
    assert second.record.id == first.record.id
    assert second.record.daily_revenue == 175


async def test_existing_snapshot_survives_current_category_edits(
    ledger_context: LedgerContext,
) -> None:
    service = LedgerService(ledger_context.session)
    await service.upsert(
        store_id=ledger_context.store_id,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context),
        actor_id=ledger_context.user_id,
    )
    ledger_context.cash.name = "Renamed"
    ledger_context.cash.include_in_total = False
    ledger_context.cash.sort_order = 9
    ledger_context.agency.name = "Agency renamed"
    ledger_context.agency.include_in_total = True
    ledger_context.agency.sort_order = 8
    await ledger_context.session.commit()

    result = await service.upsert(
        store_id=ledger_context.store_id,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context, cash=125, agency=75),
        actor_id=ledger_context.user_id,
    )

    assert result.record.daily_revenue == 125
    assert [
        (item.category_name, item.include_in_total, item.sort_order)
        for item in result.record.items
    ] == [("Cash", True, 0), ("Agency", False, 1)]


async def test_new_composed_record_requires_each_active_category_once(
    ledger_context: LedgerContext,
) -> None:
    payload = composed_payload(ledger_context)
    payload["items"] = payload["items"][:1]
    with pytest.raises(HTTPException) as exc_info:
        await LedgerService(ledger_context.session).upsert(
            store_id=ledger_context.store_id,
            record_date=ledger_context.today,
            payload=payload,
            actor_id=ledger_context.user_id,
        )
    assert exc_info.value.status_code == 422


async def test_rest_day_zeros_total_wash_and_all_items(
    ledger_context: LedgerContext,
) -> None:
    payload = composed_payload(ledger_context)
    payload["is_open"] = "休息"
    result = await LedgerService(ledger_context.session).upsert(
        store_id=ledger_context.store_id,
        record_date=ledger_context.today,
        payload=payload,
        actor_id=ledger_context.user_id,
    )
    assert result.record.daily_revenue == 0
    assert result.record.wash_count == 0
    assert {item.amount for item in result.record.items} == {0}


async def test_legacy_total_uses_integer_and_rejects_items(
    db_session: AsyncSession, user_factory, store_factory
) -> None:
    user = await user_factory(
        username="direct-user", password="secret", role="admin"
    )
    store = await store_factory(name="Direct", timezone="Europe/Berlin")
    user_id, store_id, timezone = user.id, store.id, store.timezone
    await db_session.commit()
    result = await LedgerService(db_session).upsert(
        store_id=store_id,
        record_date=datetime.now(ZoneInfo(timezone)).date(),
        payload={"is_open": "营业", "daily_revenue": 125, "items": []},
        actor_id=user_id,
    )
    assert result.record.income_mode == "legacy_total"
    assert result.record.daily_revenue == 125


async def test_future_date_and_duplicate_categories_do_not_write(
    ledger_context: LedgerContext,
) -> None:
    service = LedgerService(ledger_context.session)
    with pytest.raises(HTTPException):
        await service.upsert(
            store_id=ledger_context.store_id,
            record_date=date(2999, 1, 1),
            payload=composed_payload(ledger_context),
            actor_id=ledger_context.user_id,
        )
    duplicate = composed_payload(ledger_context)
    duplicate["items"][1]["category_id"] = ledger_context.cash_id
    with pytest.raises(HTTPException):
        await service.upsert(
            store_id=ledger_context.store_id,
            record_date=ledger_context.today,
            payload=duplicate,
            actor_id=ledger_context.user_id,
        )
    assert (
        await ledger_context.session.scalar(
            select(func.count()).select_from(StoreDailyRecord)
        )
        == 0
    )


async def test_delete_removes_current_record(ledger_context: LedgerContext) -> None:
    service = LedgerService(ledger_context.session)
    result = await service.upsert(
        store_id=ledger_context.store_id,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context),
        actor_id=ledger_context.user_id,
    )
    record_id = result.record.id
    event = await service.delete(
        store_id=ledger_context.store_id,
        record_date=ledger_context.today,
        actor_id=ledger_context.user_id,
    )
    assert event.operation == "deleted"
    assert await ledger_context.session.get(StoreDailyRecord, record_id) is None


async def test_same_day_creates_are_serialized_to_one_current_record() -> None:
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    async with async_session_factory() as setup:
        user = User(
            username="concurrent-ledger",
            password_hash="unused",
            role="admin",
            is_active=True,
        )
        store = Store(
            name="Concurrent",
            address="Concurrent",
            latitude=45,
            longitude=9,
            timezone="Europe/Berlin",
            is_active=True,
            income_items_enabled=False,
        )
        setup.add_all([user, store])
        await setup.commit()
        user_id, store_id = user.id, store.id
        timezone = store.timezone

    async def write(total: int):
        async with async_session_factory() as session:
            return await LedgerService(session).upsert(
                store_id=store_id,
                record_date=datetime.now(ZoneInfo(timezone)).date(),
                payload={"is_open": "营业", "daily_revenue": total, "items": []},
                actor_id=user_id,
            )

    results = await asyncio.gather(write(100), write(200))
    assert sorted(result.created for result in results) == [False, True]
    async with async_session_factory() as verify:
        assert await verify.scalar(select(func.count()).select_from(StoreDailyRecord)) == 1


async def test_new_record_reloads_composed_config_after_waiting_for_lock() -> None:
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    async with async_session_factory() as setup:
        user = User(
            username="stale-config-ledger",
            password_hash="unused",
            role="admin",
            is_active=True,
        )
        store = Store(
            name="Stale configuration",
            address="Stale configuration",
            latitude=45,
            longitude=9,
            timezone="Europe/Berlin",
            is_active=True,
            income_items_enabled=False,
        )
        setup.add_all([user, store])
        await setup.commit()
        user_id, store_id = user.id, store.id

    async with async_session_factory() as ledger_session:
        stale_store = await ledger_session.get(Store, store_id)
        actor = await ledger_session.get(User, user_id)
        assert stale_store is not None
        assert actor is not None
        assert stale_store.income_items_enabled is False

        async with async_session_factory() as config_session:
            async with SQLITE_WRITE_LOCK:
                configured = await IncomeConfigService(config_session).replace(
                    store_id,
                    IncomeConfigPublishBody(
                        enabled=True,
                        items=[
                            {"name": "Cash", "include_in_total": True},
                            {"name": "Agency", "include_in_total": False},
                        ],
                    ),
                )
                await config_session.commit()

        timezone = stale_store.timezone
        result = await LedgerService(ledger_session).upsert(
            store_id=store_id,
            record_date=datetime.now(ZoneInfo(timezone)).date(),
            payload={
                "is_open": "营业",
                "daily_revenue": None,
                "items": [
                    {"category_id": configured.items[0].id, "amount": 200},
                    {"category_id": configured.items[1].id, "amount": 80},
                ],
            },
            actor_id=user_id,
        )

    assert result.record.income_mode == "composed"
    assert result.record.daily_revenue == 200
    assert [
        (item.category_name, item.include_in_total, item.sort_order, item.amount)
        for item in result.record.items
    ] == [
        ("Cash", True, 0, 200),
        ("Agency", False, 1, 80),
    ]
