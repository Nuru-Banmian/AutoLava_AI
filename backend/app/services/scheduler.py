import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import logging
from pathlib import Path
from time import monotonic
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import sqlite_short_write
from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.operations import ScheduledTaskLog, UTC_TIMESTAMP_CONTRACT
from app.services.briefing import BriefingService
from app.services.operations_retention import prune_operational_rows
from app.services.sqlite_backup import backup_sqlite
from app.services.weather import FrozenWeatherLocation, WeatherResult, WeatherService, is_valid_weather_result


logger = logging.getLogger(__name__)


def apply_refreshed_weather(record: StoreDailyRecord, result: WeatherResult) -> None:
    if not is_valid_weather_result(result):
        return
    record.weather_auto = result.weather
    record.weather_code = result.weather_code
    record.temperature_max = result.temperature_max
    record.temperature_min = result.temperature_min
    record.precipitation = result.precipitation
    if not record.weather_edited and record.weather is None:
        record.weather = result.weather


class BackgroundRefreshScheduler:
    def __init__(
        self,
        refresh: Callable[[], Awaitable[None]],
        *,
        interval_seconds: float = 3600,
        timeout_seconds: float | None = None,
    ):
        self.refresh = refresh
        self.interval_seconds = interval_seconds
        self.timeout_seconds = timeout_seconds
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(
                self._run(), name="autolava-background-refresh"
            )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _run(self) -> None:
        while True:
            started_clock = monotonic()
            try:
                if self.timeout_seconds is None:
                    await self.refresh()
                else:
                    await asyncio.wait_for(
                        self.refresh(), timeout=self.timeout_seconds
                    )
            except Exception as error:
                logger.error("task=weather_refresh store_id=none result=failed duration_ms=%d error_type=%s", round((monotonic() - started_clock) * 1000), type(error).__name__)
            await asyncio.sleep(self.interval_seconds)


class DailyScheduler:
    def __init__(
        self,
        callback: Callable[[], Awaitable[None]],
        *,
        timezone: str | ZoneInfo,
        hour: int = 3,
        startup_complete: Callable[[date], bool] = lambda _today: False,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
        sleeper: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ):
        if not 0 <= hour <= 23:
            raise ValueError("hour must be between 0 and 23")
        self.callback = callback
        self.timezone = ZoneInfo(timezone) if isinstance(timezone, str) else timezone
        self.hour = hour
        self.startup_complete = startup_complete
        self.clock = clock
        self.sleeper = sleeper
        self._task: asyncio.Task[None] | None = None

    @property
    def running(self) -> bool:
        return self._task is not None and not self._task.done()

    def start(self) -> None:
        if not self.running:
            self._task = asyncio.create_task(
                self._run(), name="autolava-daily-maintenance"
            )

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    def _local_now(self) -> datetime:
        now = self.clock()
        if now.tzinfo is None:
            now = now.replace(tzinfo=UTC)
        return now.astimezone(self.timezone)

    def _seconds_until_next_run(self) -> float:
        now = self._local_now()
        next_run = now.replace(
            hour=self.hour, minute=0, second=0, microsecond=0
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        return (
            next_run.astimezone(UTC) - now.astimezone(UTC)
        ).total_seconds()

    async def _invoke_callback(self) -> None:
        started_clock = monotonic()
        try:
            await self.callback()
        except Exception as error:
            logger.error("task=sqlite_maintenance store_id=none result=failed duration_ms=%d error_type=%s", round((monotonic() - started_clock) * 1000), type(error).__name__)

    async def _run(self) -> None:
        today = self._local_now().date()
        if not self.startup_complete(today):
            await self._invoke_callback()
        while True:
            await self.sleeper(self._seconds_until_next_run())
            await self._invoke_callback()


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(UTC).replace(tzinfo=None)


def _safe_backup_error(error: Exception) -> str:
    return f"SQLite backup failed: {type(error).__name__}"


def make_sqlite_maintenance_callback(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    source: Path,
    destination: Path,
    timezone: ZoneInfo,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> Callable[[], Awaitable[None]]:
    async def maintain() -> None:
        started_clock = monotonic()
        started_value = clock()
        started_at = _utc_naive(started_value)
        if started_value.tzinfo is None:
            local_today = started_value.replace(tzinfo=UTC).astimezone(timezone).date()
        else:
            local_today = started_value.astimezone(timezone).date()
        status = "success"
        try:
            await asyncio.to_thread(
                backup_sqlite, source, destination, local_today
            )
            message = "SQLite backup completed"
        except Exception as error:
            status = "failed"
            message = _safe_backup_error(error)
        finished_at = _utc_naive(clock())
        duration_ms = round((monotonic() - started_clock) * 1000)
        logger.info("task=sqlite_backup store_id=none result=%s duration_ms=%d", status, duration_ms)

        try:
            async with session_factory() as session:
                async with sqlite_short_write(session):
                    session.add(
                        ScheduledTaskLog(
                            store_id=None,
                            task_type="sqlite_backup",
                            status=status,
                            message=message,
                            retry_count=0,
                            started_at=started_at,
                            finished_at=finished_at,
                            created_at=started_at,
                            timestamp_contract=UTC_TIMESTAMP_CONTRACT,
                        )
                    )
        except Exception as error:
            logger.error("task=sqlite_backup_log result=failed error_type=%s", type(error).__name__)

        retention_now = _utc_naive(clock())
        try:
            async with session_factory() as session:
                async with sqlite_short_write(session):
                    await prune_operational_rows(session, retention_now)
        except Exception as error:
            logger.error(
                "task=operations_retention result=failed error_type=%s",
                type(error).__name__,
            )

    return maintain


@dataclass(frozen=True)
class _StoreWeather:
    store: FrozenWeatherLocation
    started_clock: float
    today: date
    dates: tuple[date, date, date]
    results: dict[date, WeatherResult | None]


def make_refresh_callback(
    session_factory: async_sessionmaker[AsyncSession],
    weather_service: WeatherService,
    *,
    store_concurrency: int = 1,
    weather_timeout_seconds: float = 9,
) -> Callable[[], Awaitable[None]]:
    # Kept as a compatibility argument; SQLite store writes are always serialized.
    del store_concurrency

    class CachedWeatherService:
        def __init__(self, results: dict[date, WeatherResult | None]):
            self.results = results

        async def get_daily(self, store: Store, target: date) -> WeatherResult | None:
            return self.results.get(target)

    async def fetch_weather(store: Store) -> _StoreWeather:
        started_clock = monotonic()
        location = FrozenWeatherLocation.from_store(store)
        today = datetime.now(ZoneInfo(location.timezone)).date()
        dates = (today - timedelta(days=1), today, today + timedelta(days=1))

        async def lookup(target: date) -> WeatherResult | None:
            try:
                return await asyncio.wait_for(
                    weather_service.get_daily(location, target),
                    timeout=weather_timeout_seconds,
                )
            except (TimeoutError, httpx.HTTPError):
                return None

        values = await asyncio.gather(*(lookup(target) for target in dates))
        return _StoreWeather(
            store=location,
            started_clock=started_clock,
            today=today,
            dates=dates,
            results=dict(zip(dates, values, strict=True)),
        )

    async def write_store(weather: _StoreWeather) -> str:
        async with session_factory() as session:
            try:
                async with sqlite_short_write(session):
                    current_store = await session.get(Store, weather.store.id, populate_existing=True)
                    if (
                        current_store is None
                        or not current_store.is_active
                        or FrozenWeatherLocation.from_store(current_store) != weather.store
                    ):
                        return "failed"
                    # This query happens after all network waits, so manual edits made
                    # while weather was in flight are observed before automatic writes.
                    records = list(
                        await session.scalars(
                            select(StoreDailyRecord).where(
                                StoreDailyRecord.store_id == weather.store.id,
                                StoreDailyRecord.date.in_(weather.dates[:2]),
                            )
                        )
                    )
                    for record in records:
                        result = weather.results[record.date]
                        if result is not None and record.weather_refresh_due_at is None:
                            apply_refreshed_weather(record, result)
                    await BriefingService(
                        session, CachedWeatherService(weather.results)
                    ).regenerate(
                        weather.store.id,
                        ["yesterday", "today", "tomorrow"],
                        local_date=weather.today,
                    )
                    succeeded = all(
                        result is not None for result in weather.results.values()
                    )
                return "success" if succeeded else "degraded"
            except Exception as error:
                logger.error("task=weather_refresh store_id=%d result=failed error_type=%s", weather.store.id, type(error).__name__)
                return "failed"

    async def refresh_all() -> None:
        started_at = datetime.now(UTC).replace(tzinfo=None)
        discovery_failed = False
        try:
            async with session_factory() as session:
                stores = list(
                    await session.scalars(
                        select(Store)
                        .where(Store.is_active.is_(True))
                        .order_by(Store.id)
                    )
                )
        except Exception as error:
            stores = []
            discovery_failed = True
            logger.error("task=weather_refresh store_id=none result=failed error_type=%s", type(error).__name__)

        started_clock = monotonic()
        outcomes: list[str] = []
        for offset in range(0, len(stores), 20):
            batch = stores[offset:offset + 20]
            fetched = await asyncio.gather(
                *(fetch_weather(store) for store in batch), return_exceptions=True
            )
            for store, result in zip(batch, fetched, strict=True):
                if isinstance(result, BaseException):
                    if isinstance(result, asyncio.CancelledError):
                        raise result
                    outcomes.append("failed")
                    logger.error(
                        "task=weather_refresh store_id=%d result=failed duration_ms=%d error_type=%s",
                        store.id, round((monotonic() - started_clock) * 1000), type(result).__name__,
                    )
                    continue
                outcome = await write_store(result)
                outcomes.append(outcome)
                logger.info(
                    "task=weather_refresh store_id=%d result=%s duration_ms=%d",
                    result.store.id, outcome, round((monotonic() - result.started_clock) * 1000),
                )
        succeeded = outcomes.count("success")
        degraded = outcomes.count("degraded")
        failed = len(stores) - succeeded - degraded
        logger.info("task=weather_refresh store_id=all result=%s duration_ms=%d", "failed" if discovery_failed or failed else "degraded" if degraded else "success", round((monotonic() - started_clock) * 1000))
        if discovery_failed:
            status = "failed"
            message = "天气刷新失败：无法读取启用门店"
        elif not stores:
            status = "success"
            message = "天气刷新完成：当前没有启用门店"
        else:
            status = "failed" if failed else "degraded" if degraded else "success"
            message = (
                f"天气刷新完成：共 {len(stores)} 个门店，"
                f"成功 {succeeded} 个，降级 {degraded} 个，失败 {failed} 个"
            )

        async with session_factory() as session:
            async with sqlite_short_write(session):
                session.add(
                    ScheduledTaskLog(
                        store_id=None,
                        task_type="weather_refresh",
                        status=status,
                        message=message,
                        retry_count=0,
                        started_at=started_at,
                        finished_at=datetime.now(UTC).replace(tzinfo=None),
                        created_at=started_at,
                        timestamp_contract=UTC_TIMESTAMP_CONTRACT,
                    )
                )

    return refresh_all
