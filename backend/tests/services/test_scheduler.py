import asyncio
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

from app.core.database import async_session_factory, engine
from app.models.base import Base
from app.models.identity import Store, User
from app.models.ledger import StoreDailyRecord
from app.main import create_app
from app.services.scheduler import (
    BackgroundRefreshScheduler,
    apply_refreshed_weather,
    make_refresh_callback,
    make_retention_callback,
)
from app.services.retention import RetentionResult
from app.services.weather import WeatherResult


def test_refreshed_weather_preserves_user_edited_final_value() -> None:
    record = StoreDailyRecord(weather="手工天气", weather_auto="旧天气", weather_edited=True)

    apply_refreshed_weather(record, WeatherResult("晴", 0, 30.0, 20.0, 0.0))

    assert record.weather == "手工天气"
    assert record.weather_auto == "晴"
    assert record.weather_code == 0


async def test_background_refresh_is_bounded_and_can_be_stopped() -> None:
    async def hang() -> None:
        await asyncio.sleep(60)

    never_finishes = AsyncMock(side_effect=hang)
    scheduler = BackgroundRefreshScheduler(
        never_finishes, interval_seconds=0.01, timeout_seconds=0.01
    )

    scheduler.start()
    await asyncio.sleep(0.04)
    await scheduler.stop()

    assert never_finishes.await_count >= 1
    assert scheduler.running is False


async def test_background_refresh_survives_weather_failure() -> None:
    failure = AsyncMock(side_effect=RuntimeError("weather offline"))
    scheduler = BackgroundRefreshScheduler(failure, interval_seconds=0.01, timeout_seconds=0.1)

    scheduler.start()
    await asyncio.sleep(0.04)
    await scheduler.stop()

    assert failure.await_count >= 2
    assert scheduler.running is False


async def test_app_lifespan_starts_and_stops_background_refresh() -> None:
    app = create_app()
    scheduler = app.state.background_refresh_scheduler
    retention_scheduler = app.state.background_retention_scheduler
    scheduler.refresh = AsyncMock()
    retention_scheduler.refresh = AsyncMock()

    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        assert scheduler.running is True
        assert retention_scheduler.running is True
        assert retention_scheduler.interval_seconds == 86400

    assert scheduler.running is False
    assert retention_scheduler.running is False


async def test_retention_callback_logs_success(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeSession:
        def __init__(self):
            self.added = []
            self.commit = AsyncMock()
            self.rollback = AsyncMock()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        def add(self, value):
            self.added.append(value)

    session = FakeSession()
    prune = AsyncMock(return_value=RetentionResult(ledger_snapshots_pruned=2, config_versions_pruned=3))
    monkeypatch.setattr("app.services.scheduler.RetentionService.prune", prune)

    await make_retention_callback(lambda: session)()

    assert prune.await_count == 1
    assert session.commit.await_count == 1
    assert session.added[0].task_type == "retention_cleanup"
    assert session.added[0].status == "success"
    assert session.added[0].timestamp_contract == "utc_v1"
    assert "2 ledger snapshots" in session.added[0].message


async def test_refresh_rechecks_weather_edited_after_network_wait() -> None:
    if engine.dialect.name != "mysql" or engine.url.database != "autolava_test":
        pytest.fail("Concurrency test requires the dedicated autolava_test database")
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    async with async_session_factory() as setup:
        user = User(
            username="scheduler-race",
            password_hash="unused",
            role="admin",
            is_active=True,
            remember_token=None,
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
            daily_revenue=Decimal("0.00"),
            wash_count=None,
            is_open="营业",
            weather="旧天气",
            weather_auto="旧天气",
            weather_code=3,
            temperature_max=Decimal("20.00"),
            temperature_min=Decimal("10.00"),
            precipitation=Decimal("0.00"),
            activity=None,
            weather_edited=False,
            scanned=False,
            created_by=user.id,
            updated_by=user.id,
        )
        setup.add(record)
        await setup.commit()
        store_id, record_id = store.id, record.id

    weather_started = asyncio.Event()
    release_weather = asyncio.Event()

    class ControlledWeather:
        calls = 0

        async def get_daily(self, store, requested_date):
            self.calls += 1
            if self.calls == 1:
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
        refreshed = await verify.scalar(
            select(StoreDailyRecord).where(StoreDailyRecord.id == record_id)
        )
        assert refreshed is not None
        assert refreshed.store_id == store_id
        assert refreshed.weather_edited is True
        assert refreshed.weather == "用户手工天气"
        assert refreshed.weather_auto == "晴"


async def test_refresh_callback_isolates_failure_and_progresses_other_stores() -> None:
    if engine.dialect.name != "mysql" or engine.url.database != "autolava_test":
        pytest.fail("Concurrency test requires the dedicated autolava_test database")
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    async with async_session_factory() as setup:
        stores = [
            Store(
                name=name,
                address=f"{name} address",
                latitude=Decimal("45.000000"),
                longitude=Decimal("9.000000"),
                timezone="Europe/Berlin",
                is_active=True,
            )
            for name in ("Slow", "Failed", "Healthy")
        ]
        setup.add_all(stores)
        await setup.commit()
        slow_id, failed_id, healthy_id = (store.id for store in stores)

    healthy_started = asyncio.Event()
    calls: dict[int, set] = {slow_id: set(), failed_id: set(), healthy_id: set()}

    class CoordinatedWeather:
        async def get_daily(self, store, target):
            calls[store.id].add(target)
            if store.id == slow_id:
                await healthy_started.wait()
            if store.id == failed_id:
                raise RuntimeError("one store weather failed")
            if store.id == healthy_id:
                healthy_started.set()
            return WeatherResult("晴", 0, 30.0, 20.0, 0.0)

    refresh = make_refresh_callback(async_session_factory, CoordinatedWeather())
    await asyncio.wait_for(refresh(), timeout=1)

    assert healthy_started.is_set()
    assert len(calls[slow_id]) == 3
    assert len(calls[failed_id]) == 3
    assert len(calls[healthy_id]) == 3
