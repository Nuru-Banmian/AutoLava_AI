import asyncio
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
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
        timeout_seconds: float = 30,
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
                await asyncio.wait_for(self.refresh(), timeout=self.timeout_seconds)
            except Exception:
                pass
            await asyncio.sleep(self.interval_seconds)


def make_refresh_callback(
    session_factory: async_sessionmaker[AsyncSession], weather_service: WeatherService
) -> Callable[[], Awaitable[None]]:
    async def refresh_all() -> None:
        async with session_factory() as session:
            stores = list(
                await session.scalars(
                    select(Store).where(Store.is_active.is_(True)).order_by(Store.id)
                )
            )
            for store in stores:
                try:
                    today = datetime.now(ZoneInfo(store.timezone)).date()
                    records = list(
                        await session.scalars(
                            select(StoreDailyRecord)
                            .where(
                                StoreDailyRecord.store_id == store.id,
                                StoreDailyRecord.date.in_([today - timedelta(days=1), today]),
                            )
                            .options(selectinload(StoreDailyRecord.items))
                        )
                    )
                    for record in records:
                        result = await weather_service.get_daily(store, record.date)
                        if result is not None:
                            apply_refreshed_weather(record, result)
                    await session.flush()
                    await BriefingService(session, weather_service).regenerate(
                        store.id, ["yesterday", "today", "tomorrow"], local_date=today
                    )
                except Exception:
                    await session.rollback()

    return refresh_all
