import asyncio
from dataclasses import dataclass
from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.models.base import Base
from app.models.identity import Store, User
from app.models.ledger import IncomeCategory, StoreDailyRecord
from app.services.ledger import LedgerService


@dataclass
class LedgerContext:
    session: AsyncSession
    user: User
    store: Store
    cash: IncomeCategory
    agency: IncomeCategory

    @property
    def today(self) -> date:
        return datetime.now(ZoneInfo(self.store.timezone)).date()


@pytest.fixture
async def ledger_context(db_session, user_factory, store_factory) -> LedgerContext:
    user = await user_factory(username="ledger-user", password="secret")
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
    await db_session.flush()
    return LedgerContext(db_session, user, store, cash, agency)


def composed_payload(context: LedgerContext, *, cash: int = 100, agency: int = 50) -> dict:
    return {
        "is_open": "营业",
        "daily_revenue": None,
        "wash_count": 3,
        "weather": "晴",
        "weather_edited": False,
        "activity": None,
        "items": [
            {"category_id": context.cash.id, "amount": cash},
            {"category_id": context.agency.id, "amount": agency},
        ],
    }


async def test_composed_total_sums_only_included_integer_items(
    ledger_context: LedgerContext,
) -> None:
    result = await LedgerService(ledger_context.session).upsert(
        store=ledger_context.store,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context),
        actor=ledger_context.user,
    )
    assert result.record.daily_revenue == 100
    assert [item.amount for item in result.record.items] == [100, 50]


async def test_second_write_directly_overwrites_existing_record(
    ledger_context: LedgerContext,
) -> None:
    service = LedgerService(ledger_context.session)
    first = await service.upsert(
        store=ledger_context.store,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context),
        actor=ledger_context.user,
    )
    second = await service.upsert(
        store=ledger_context.store,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context, cash=175),
        actor=ledger_context.user,
    )
    assert second.created is False
    assert second.record.id == first.record.id
    assert second.record.daily_revenue == 175


async def test_existing_snapshot_survives_current_category_edits(
    ledger_context: LedgerContext,
) -> None:
    service = LedgerService(ledger_context.session)
    await service.upsert(
        store=ledger_context.store,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context),
        actor=ledger_context.user,
    )
    ledger_context.cash.name = "Renamed"
    ledger_context.cash.include_in_total = False
    ledger_context.cash.sort_order = 9
    ledger_context.agency.name = "Agency renamed"
    ledger_context.agency.include_in_total = True
    ledger_context.agency.sort_order = 8
    await ledger_context.session.flush()

    result = await service.upsert(
        store=ledger_context.store,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context, cash=125, agency=75),
        actor=ledger_context.user,
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
            store=ledger_context.store,
            record_date=ledger_context.today,
            payload=payload,
            actor=ledger_context.user,
        )
    assert exc_info.value.status_code == 422


async def test_rest_day_zeros_total_wash_and_all_items(
    ledger_context: LedgerContext,
) -> None:
    payload = composed_payload(ledger_context)
    payload["is_open"] = "休息"
    result = await LedgerService(ledger_context.session).upsert(
        store=ledger_context.store,
        record_date=ledger_context.today,
        payload=payload,
        actor=ledger_context.user,
    )
    assert result.record.daily_revenue == 0
    assert result.record.wash_count == 0
    assert {item.amount for item in result.record.items} == {0}


async def test_legacy_total_uses_integer_and_rejects_items(
    db_session: AsyncSession, user_factory, store_factory
) -> None:
    user = await user_factory(username="direct-user", password="secret")
    store = await store_factory(name="Direct", timezone="Europe/Berlin")
    result = await LedgerService(db_session).upsert(
        store=store,
        record_date=datetime.now(ZoneInfo(store.timezone)).date(),
        payload={"is_open": "营业", "daily_revenue": 125, "items": []},
        actor=user,
    )
    assert result.record.income_mode == "legacy_total"
    assert result.record.daily_revenue == 125


async def test_future_date_and_duplicate_categories_do_not_write(
    ledger_context: LedgerContext,
) -> None:
    service = LedgerService(ledger_context.session)
    with pytest.raises(HTTPException):
        await service.upsert(
            store=ledger_context.store,
            record_date=date(2999, 1, 1),
            payload=composed_payload(ledger_context),
            actor=ledger_context.user,
        )
    duplicate = composed_payload(ledger_context)
    duplicate["items"][1]["category_id"] = ledger_context.cash.id
    with pytest.raises(HTTPException):
        await service.upsert(
            store=ledger_context.store,
            record_date=ledger_context.today,
            payload=duplicate,
            actor=ledger_context.user,
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
        store=ledger_context.store,
        record_date=ledger_context.today,
        payload=composed_payload(ledger_context),
        actor=ledger_context.user,
    )
    event = await service.delete(
        store=ledger_context.store,
        record_date=ledger_context.today,
        actor=ledger_context.user,
    )
    assert event.operation == "deleted"
    assert await ledger_context.session.get(StoreDailyRecord, result.record.id) is None


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

    async def write(total: int):
        async with async_session_factory() as session:
            return await LedgerService(session).upsert(
                store=store,
                record_date=datetime.now(ZoneInfo(store.timezone)).date(),
                payload={"is_open": "营业", "daily_revenue": total, "items": []},
                actor=user,
            )

    results = await asyncio.gather(write(100), write(200))
    assert sorted(result.created for result in results) == [False, True]
    async with async_session_factory() as verify:
        assert await verify.scalar(select(func.count()).select_from(StoreDailyRecord)) == 1
