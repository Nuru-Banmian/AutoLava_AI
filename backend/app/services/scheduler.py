import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

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
            self._task = asyncio.create_task(self._run(), name="autolava-background-refresh")

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
                    await asyncio.wait_for(self.refresh(), timeout=self.timeout_seconds)
            except Exception:
                pass
            await asyncio.sleep(self.interval_seconds)


def make_refresh_callback(
    session_factory: async_sessionmaker[AsyncSession],
    weather_service: WeatherService,
    *,
    store_concurrency: int = 4,
    weather_timeout_seconds: float = 9,
) -> Callable[[], Awaitable[None]]:
    class CachedWeatherService:
        def __init__(self, results: dict[date, WeatherResult | None]):
            self.results = results

        async def get_daily(self, store: Store, target: date) -> WeatherResult | None:
            return self.results.get(target)

    async def refresh_store(store: Store) -> bool:
        today = datetime.now(ZoneInfo(store.timezone)).date()
        weather_dates = [today - timedelta(days=1), today, today + timedelta(days=1)]

        async def lookup(target: date) -> WeatherResult | None:
            try:
                return await asyncio.wait_for(
                    weather_service.get_daily(store, target),
                    timeout=weather_timeout_seconds,
                )
            except Exception:
                return None

        weather_values = await asyncio.gather(*(lookup(target) for target in weather_dates))
        results = dict(zip(weather_dates, weather_values, strict=True))
        cached_weather = CachedWeatherService(results)
        async with session_factory() as session:
            try:
                records = list(
                    await session.scalars(
                        select(StoreDailyRecord)
                        .where(
                            StoreDailyRecord.store_id == store.id,
                            StoreDailyRecord.date.in_(weather_dates[:2]),
                        )
                        .with_for_update()
                    )
                )
                for record in records:
                    result = results[record.date]
                    if result is not None:
                        apply_refreshed_weather(record, result)
                await session.flush()
                await BriefingService(session, cached_weather).regenerate(
                    store.id, ["yesterday", "today", "tomorrow"], local_date=today
                )
                await session.commit()
                return all(result is not None for result in weather_values)
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
                        select(Store).where(Store.is_active.is_(True)).order_by(Store.id)
                    )
                )
        except Exception:
            stores = []
            discovery_failed = True
        semaphore = asyncio.Semaphore(store_concurrency)

        async def bounded_refresh(store: Store) -> bool:
            async with semaphore:
                try:
                    return await refresh_store(store)
                except Exception:
                    return False

        outcomes = await asyncio.gather(*(bounded_refresh(store) for store in stores))
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

    return refresh_all
