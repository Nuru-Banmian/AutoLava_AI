import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import SQLITE_WRITE_LOCK
from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.operations import ScheduledTaskLog, UTC_TIMESTAMP_CONTRACT
from app.services.briefing import BriefingService
from app.services.weather import WeatherResult, WeatherService


def apply_refreshed_weather(record: StoreDailyRecord, result: WeatherResult) -> None:
    record.weather_auto = result.weather
    record.weather_code = result.weather_code
    record.temperature_max = result.temperature_max
    record.temperature_min = result.temperature_min
    record.precipitation = result.precipitation
    if not record.weather_edited:
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
            try:
                if self.timeout_seconds is None:
                    await self.refresh()
                else:
                    await asyncio.wait_for(
                        self.refresh(), timeout=self.timeout_seconds
                    )
            except Exception:
                pass
            await asyncio.sleep(self.interval_seconds)


@dataclass(frozen=True)
class _StoreWeather:
    store: Store
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
        today = datetime.now(ZoneInfo(store.timezone)).date()
        dates = (today - timedelta(days=1), today, today + timedelta(days=1))

        async def lookup(target: date) -> WeatherResult | None:
            try:
                return await asyncio.wait_for(
                    weather_service.get_daily(store, target),
                    timeout=weather_timeout_seconds,
                )
            except Exception:
                return None

        values = await asyncio.gather(*(lookup(target) for target in dates))
        return _StoreWeather(
            store=store,
            today=today,
            dates=dates,
            results=dict(zip(dates, values, strict=True)),
        )

    async def write_store(weather: _StoreWeather) -> bool:
        async with session_factory() as session:
            async with SQLITE_WRITE_LOCK:
                try:
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
                        if result is not None:
                            apply_refreshed_weather(record, result)
                    await BriefingService(
                        session, CachedWeatherService(weather.results)
                    ).regenerate(
                        weather.store.id,
                        ["yesterday", "today", "tomorrow"],
                        local_date=weather.today,
                    )
                    await session.commit()
                    return all(
                        result is not None for result in weather.results.values()
                    )
                except Exception:
                    await session.rollback()
                    return False

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
        except Exception:
            stores = []
            discovery_failed = True

        fetched = await asyncio.gather(*(fetch_weather(store) for store in stores))
        outcomes = [
            await write_store(weather)
            for weather in sorted(fetched, key=lambda value: value.store.id)
        ]
        succeeded = sum(outcomes)
        failed = len(stores) - succeeded
        if discovery_failed:
            status = "failed"
            message = "天气刷新失败：无法读取启用门店"
        elif not stores:
            status = "success"
            message = "天气刷新完成：当前没有启用门店"
        else:
            status = "success" if failed == 0 else "failed"
            message = (
                f"天气刷新完成：共 {len(stores)} 个门店，"
                f"成功 {succeeded} 个，失败 {failed} 个"
            )

        async with session_factory() as session:
            async with SQLITE_WRITE_LOCK:
                try:
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
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

    return refresh_all
