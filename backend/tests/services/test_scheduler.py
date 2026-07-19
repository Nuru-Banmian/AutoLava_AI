import asyncio
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.models.base import Base
from app.models.identity import Store, User
from app.models.ledger import StoreDailyRecord
from app.models.operations import ScheduledTaskLog
from app.services.briefing import BriefingService
from app.services.scheduler import (
    BackgroundRefreshScheduler,
    apply_refreshed_weather,
    make_refresh_callback,
)
from app.services.ledger import LedgerService
from app.services.weather import WeatherResult


async def _reset_database() -> None:
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())


def test_refreshed_weather_preserves_user_edited_final_value() -> None:
    record = StoreDailyRecord(
        weather="手工天气", weather_auto="旧天气", weather_edited=True
    )
    apply_refreshed_weather(record, WeatherResult("晴", 0, 30.0, 20.0, 0.0))
    assert record.weather == "手工天气"
    assert record.weather_auto == "晴"


async def test_background_refresh_is_bounded_and_can_be_stopped() -> None:
    async def hang() -> None:
        await asyncio.sleep(60)

    refresh = AsyncMock(side_effect=hang)
    scheduler = BackgroundRefreshScheduler(
        refresh, interval_seconds=0.01, timeout_seconds=0.01
    )
    scheduler.start()
    await asyncio.sleep(0.04)
    await scheduler.stop()
    assert refresh.await_count >= 1
    assert scheduler.running is False


async def test_refresh_rechecks_weather_edited_after_network_wait() -> None:
    await _reset_database()
    async with async_session_factory() as setup:
        user = User(
            username="scheduler-race",
            password_hash="unused",
            role="admin",
            is_active=True,
        )
        store = Store(
            name="Race",
            address="Race address",
            latitude=Decimal("45.000000"),
            longitude=Decimal("9.000000"),
            timezone="Europe/Berlin",
            is_active=True,
        )
        setup.add_all([user, store])
        await setup.flush()
        target = datetime.now(ZoneInfo(store.timezone)).date()
        record = StoreDailyRecord(
            store_id=store.id,
            date=target,
            daily_revenue=0,
            is_open="营业",
            weather="旧天气",
            weather_auto="旧天气",
            weather_edited=False,
            created_by=user.id,
            updated_by=user.id,
        )
        setup.add(record)
        await setup.commit()
        record_id = record.id

    weather_started = asyncio.Event()
    release_weather = asyncio.Event()

    class ControlledWeather:
        async def get_daily(self, store, requested_date):
            weather_started.set()
            await release_weather.wait()
            return WeatherResult("晴", 0, 30.0, 20.0, 0.0)

    refresh_task = asyncio.create_task(
        make_refresh_callback(async_session_factory, ControlledWeather())()
    )
    await weather_started.wait()
    async with async_session_factory() as editor:
        current = await editor.get(StoreDailyRecord, record_id)
        assert current is not None
        current.weather = "用户手工天气"
        current.weather_edited = True
        await editor.commit()
    release_weather.set()
    await refresh_task

    async with async_session_factory() as verify:
        refreshed = await verify.get(StoreDailyRecord, record_id)
        assert refreshed is not None
        assert refreshed.weather_edited is True
        assert refreshed.weather == "用户手工天气"
        assert refreshed.weather_auto == "晴"


async def test_weather_fetches_overlap_and_store_writes_follow_id_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _reset_database()
    async with async_session_factory() as setup:
        stores = [
            Store(
                name=name,
                address=name,
                latitude=Decimal("45"),
                longitude=Decimal("9"),
                timezone="Europe/Berlin",
                is_active=True,
            )
            for name in ("One", "Two", "Three")
        ]
        setup.add_all(stores)
        await setup.commit()
        expected_order = [store.id for store in stores]

    seen_stores: set[int] = set()
    all_started = asyncio.Event()

    class ConcurrentWeather:
        async def get_daily(self, store, target):
            seen_stores.add(store.id)
            if len(seen_stores) == 3:
                all_started.set()
            await asyncio.wait_for(all_started.wait(), timeout=1)
            return WeatherResult("晴", 0, 30.0, 20.0, 0.0)

    write_order: list[int] = []

    async def record_write(service, store_id, *_args, **_kwargs):
        write_order.append(store_id)
        return []

    monkeypatch.setattr(
        "app.services.scheduler.BriefingService.regenerate", record_write
    )
    await make_refresh_callback(async_session_factory, ConcurrentWeather())()
    assert seen_stores == set(expected_order)
    assert write_order == expected_order


async def test_refresh_logs_truthful_success_when_no_stores() -> None:
    await _reset_database()
    weather = AsyncMock(side_effect=AssertionError("no stores"))
    await make_refresh_callback(async_session_factory, weather)()
    async with async_session_factory() as verify:
        task = await verify.scalar(select(ScheduledTaskLog))
        assert task is not None
        assert task.status == "success"
        assert task.message == "天气刷新完成：当前没有启用门店"
    weather.assert_not_awaited()


async def _held_ledger_write(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> tuple[asyncio.Event, asyncio.Task]:
    entered = asyncio.Event()
    release = asyncio.Event()
    target = datetime.now(ZoneInfo(store.timezone)).date()

    async def hold(*_args, **_kwargs):
        entered.set()
        await release.wait()
        return True, 456, target

    async def canonical(*_args, **_kwargs):
        return SimpleNamespace(id=456, date=target)

    monkeypatch.setattr(LedgerService, "_upsert_locked", hold)
    monkeypatch.setattr(LedgerService, "_find_record", canonical)
    task = asyncio.create_task(
        LedgerService(SimpleNamespace(rollback=None)).upsert(
            store=store,
            record_date=target,
            payload={},
            actor=SimpleNamespace(id=77),
        )
    )
    await entered.wait()
    return release, task


async def test_ledger_write_blocks_scheduler_store_write_but_not_weather_fetch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _reset_database()
    async with async_session_factory() as setup:
        store = Store(
            name="Shared lock store",
            address="Shared lock store",
            latitude=Decimal("45"),
            longitude=Decimal("9"),
            timezone="Europe/Berlin",
            is_active=True,
        )
        setup.add(store)
        await setup.commit()

    release_ledger, ledger_task = await _held_ledger_write(store, monkeypatch)
    weather_entered = asyncio.Event()
    scheduler_write_entered = asyncio.Event()

    class ObservableWeather:
        async def get_daily(self, store, target):
            weather_entered.set()
            return WeatherResult("晴", 0, 30.0, 20.0, 0.0)

    async def observe_store_write(*_args, **_kwargs):
        scheduler_write_entered.set()
        return []

    monkeypatch.setattr(BriefingService, "regenerate", observe_store_write)
    refresh_task = asyncio.create_task(
        make_refresh_callback(async_session_factory, ObservableWeather())()
    )
    await asyncio.wait_for(weather_entered.wait(), timeout=1)
    try:
        await asyncio.wait_for(scheduler_write_entered.wait(), timeout=0.05)
        was_blocked = False
    except TimeoutError:
        was_blocked = True
    release_ledger.set()
    await asyncio.gather(ledger_task, refresh_task)
    assert was_blocked is True
    assert scheduler_write_entered.is_set()


async def test_ledger_write_blocks_scheduler_task_log_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _reset_database()
    detached_store = Store(
        id=999,
        name="Lock holder",
        address="Lock holder",
        latitude=Decimal("45"),
        longitude=Decimal("9"),
        timezone="Europe/Berlin",
        is_active=False,
    )
    release_ledger, ledger_task = await _held_ledger_write(
        detached_store, monkeypatch
    )
    refresh_task = asyncio.create_task(
        make_refresh_callback(
            async_session_factory,
            AsyncMock(side_effect=AssertionError("no active stores")),
        )()
    )
    await asyncio.sleep(0.05)
    was_blocked = not refresh_task.done()
    release_ledger.set()
    await asyncio.gather(ledger_task, refresh_task)
    assert was_blocked is True
    async with async_session_factory() as verify:
        assert await verify.scalar(select(ScheduledTaskLog.id)) is not None
