"""Recoverable, bounded weather enrichment for saved ledger records."""

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
import logging
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import sqlite_short_write
from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.operations import ScheduledTaskLog, UTC_TIMESTAMP_CONTRACT
from app.services.briefing import BriefingService
from app.services.scheduler import apply_refreshed_weather
from app.services.weather import FrozenWeatherLocation, WeatherService, is_valid_weather_result

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingRecord:
    id: int
    identity: str
    revision: int
    record_date: date
    weather_edited: bool
    weather_refresh_finished: bool
    location: FrozenWeatherLocation


class PendingWeatherRefresh:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        weather_service: Callable[[], WeatherService],
        *,
        batch_size: int = 20,
        poll_seconds: float = 30,
        timeout_seconds: float = 9,
    ) -> None:
        self.session_factory = session_factory
        self.weather_service = weather_service
        self.batch_size = batch_size
        self.poll_seconds = poll_seconds
        self.timeout_seconds = timeout_seconds
        self._wake = asyncio.Event()
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._run(), name="autolava-pending-weather")

    def wake(self) -> None:
        self._wake.set()

    async def stop(self) -> None:
        if self._task is None:
            return
        self._task.cancel()
        with suppress(asyncio.CancelledError):
            await self._task
        self._task = None

    async def _discover(self) -> list[PendingRecord]:
        async with self.session_factory() as session:
            rows = await session.execute(
                select(StoreDailyRecord, Store)
                .join(Store, Store.id == StoreDailyRecord.store_id)
                .where(
                    Store.is_active.is_(True),
                    StoreDailyRecord.weather_refresh_due_at.is_not(None),
                    StoreDailyRecord.weather_refresh_due_at
                    <= datetime.now(UTC).replace(tzinfo=None),
                )
                .order_by(StoreDailyRecord.weather_refresh_due_at, StoreDailyRecord.id)
                .limit(self.batch_size)
            )
            return [
                PendingRecord(
                    id=record.id,
                    identity=record.identity,
                    revision=record.revision,
                    record_date=record.date,
                    weather_edited=record.weather_edited,
                    weather_refresh_finished=record.weather_refresh_finished,
                    location=FrozenWeatherLocation.from_store(store),
                )
                for record, store in rows
            ]

    async def _process(self, pending: PendingRecord) -> None:
        started_at = datetime.now(UTC).replace(tzinfo=None)
        result = None
        if not pending.weather_edited and not pending.weather_refresh_finished:
            try:
                result = await asyncio.wait_for(
                    self.weather_service().get_daily(pending.location, pending.record_date),
                    timeout=self.timeout_seconds,
                )
            except Exception:
                pass
        valid = result is not None and is_valid_weather_result(result)
        expected_due_at = None
        async with self.session_factory() as session:
            async with sqlite_short_write(session):
                record = await session.get(StoreDailyRecord, pending.id, populate_existing=True)
                store = await session.get(Store, pending.location.id, populate_existing=True)
                if (
                    record is None
                    or store is None
                    or not store.is_active
                    or record.identity != pending.identity
                    or record.revision != pending.revision
                    or record.weather_refresh_due_at is None
                    or FrozenWeatherLocation.from_store(store) != pending.location
                ):
                    if store is not None:
                        session.add(
                            self._task_log(store.id, pending.record_date, "skipped", started_at)
                        )
                    return
                if record.weather_edited:
                    record.weather_refresh_finished = True
                    session.add(
                        self._task_log(store.id, pending.record_date, "skipped", started_at)
                    )
                elif record.weather_refresh_finished:
                    pass
                elif valid:
                    apply_refreshed_weather(record, result)
                    record.revision += 1
                    record.weather_refresh_finished = True
                else:
                    record.weather_refresh_due_at = datetime.now(UTC).replace(
                        tzinfo=None
                    ) + timedelta(minutes=5)
                if not record.weather_edited and not pending.weather_refresh_finished:
                    session.add(
                        self._task_log(
                            store.id, record.date, "success" if valid else "failed", started_at
                        )
                    )
                expected_due_at = record.weather_refresh_due_at
        today = datetime.now(ZoneInfo(pending.location.timezone)).date()
        card_type = (
            "today"
            if pending.record_date == today
            else ("yesterday" if pending.record_date == today - timedelta(days=1) else None)
        )
        if card_type is None:
            if valid or pending.weather_edited or pending.weather_refresh_finished:
                async with self.session_factory() as session:
                    async with sqlite_short_write(session):
                        record = await session.get(
                            StoreDailyRecord, pending.id, populate_existing=True
                        )
                        if (
                            record is not None
                            and record.identity == pending.identity
                            and record.revision in (pending.revision, pending.revision + 1)
                            and record.weather_refresh_finished
                            and record.weather_refresh_due_at == expected_due_at
                        ):
                            record.weather_refresh_due_at = None
            return
        try:
            async with self.session_factory() as session:
                async with sqlite_short_write(session):
                    store = await session.get(Store, pending.location.id, populate_existing=True)
                    if store is None or FrozenWeatherLocation.from_store(store) != pending.location:
                        return
                    record = await session.scalar(
                        select(StoreDailyRecord).where(
                            StoreDailyRecord.store_id == store.id,
                            StoreDailyRecord.date == pending.record_date,
                        )
                    )

                    class CachedWeather:
                        async def get_daily(self, _store, _target):
                            return None

                    await BriefingService(session, CachedWeather()).regenerate(
                        store.id,
                        [card_type],
                        local_date=today,
                        weather_overrides={
                            pending.record_date: (
                                record.weather
                                if record is not None and record.weather is not None
                                else "天气暂时不可用"
                            )
                        },
                    )
                    if (
                        record is not None
                        and record.identity == pending.identity
                        and record.revision in (pending.revision, pending.revision + 1)
                        and record.weather_refresh_finished
                        and record.weather_refresh_due_at == expected_due_at
                    ):
                        record.weather_refresh_due_at = None
                    session.add(
                        self._task_log(
                            store.id,
                            pending.record_date,
                            "success",
                            started_at,
                            task_type="ledger_briefing_refresh",
                        )
                    )
        except Exception:
            logger.exception("Ledger briefing refresh failed after weather enrichment")
            async with self.session_factory() as session:
                async with sqlite_short_write(session):
                    record = await session.get(StoreDailyRecord, pending.id, populate_existing=True)
                    if (
                        record is not None
                        and record.identity == pending.identity
                        and record.weather_refresh_due_at is not None
                        and record.weather_refresh_due_at == expected_due_at
                        and record.revision in (pending.revision, pending.revision + 1)
                    ):
                        record.weather_refresh_due_at = datetime.now(UTC).replace(
                            tzinfo=None
                        ) + timedelta(minutes=5)
                    session.add(
                        self._task_log(
                            pending.location.id,
                            pending.record_date,
                            "failed",
                            started_at,
                            task_type="ledger_briefing_refresh",
                        )
                    )

    @staticmethod
    def _task_log(
        store_id: int,
        record_date: date,
        status: str,
        started_at: datetime,
        *,
        task_type: str = "ledger_weather_refresh",
    ) -> ScheduledTaskLog:
        return ScheduledTaskLog(
            store_id=store_id,
            task_type=task_type,
            status=status,
            message=f"{task_type} {status} for {record_date.isoformat()}",
            retry_count=0,
            started_at=started_at,
            finished_at=datetime.now(UTC).replace(tzinfo=None),
            timestamp_contract=UTC_TIMESTAMP_CONTRACT,
        )

    async def _run(self) -> None:
        while True:
            try:
                pending = await self._discover()
                if pending:
                    outcomes = await asyncio.gather(
                        *(self._process(record) for record in pending), return_exceptions=True
                    )
                    for outcome in outcomes:
                        if isinstance(outcome, Exception):
                            logger.error("Pending weather item failed: %s", type(outcome).__name__)
                    if len(pending) == self.batch_size and not any(
                        isinstance(outcome, Exception) for outcome in outcomes
                    ):
                        continue
            except Exception:
                logger.exception("Pending weather refresh failed")
            try:
                await asyncio.wait_for(self._wake.wait(), timeout=self.poll_seconds)
            except TimeoutError:
                pass
            self._wake.clear()
