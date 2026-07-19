from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.database import SQLITE_WRITE_LOCK
from app.events.ledger import LedgerChanged
from app.models.identity import Store, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord

_MAX_MONEY = 9_999_999_999


@dataclass(frozen=True)
class LedgerWriteResult:
    record: StoreDailyRecord
    created: bool
    event: LedgerChanged

    def __iter__(self):
        yield self.record
        yield self.created


class LedgerService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _local_today(store: Store) -> date:
        return datetime.now(ZoneInfo(store.timezone)).date()

    async def _find_record(
        self, *, store_id: int, record_date: date
    ) -> StoreDailyRecord | None:
        return await self.session.scalar(
            select(StoreDailyRecord)
            .where(
                StoreDailyRecord.store_id == store_id,
                StoreDailyRecord.date == record_date,
            )
            .options(selectinload(StoreDailyRecord.items))
            .execution_options(populate_existing=True)
        )

    async def get(self, *, store: Store, record_date: date) -> StoreDailyRecord:
        record = await self._find_record(store_id=store.id, record_date=record_date)
        if record is None:
            raise HTTPException(404, "Record not found")
        return record

    async def recent(self, *, store: Store, days: int = 7) -> list[StoreDailyRecord]:
        today = self._local_today(store)
        first_date = today - timedelta(days=days - 1)
        records = await self.session.scalars(
            select(StoreDailyRecord)
            .where(
                StoreDailyRecord.store_id == store.id,
                StoreDailyRecord.date >= first_date,
                StoreDailyRecord.date <= today,
            )
            .options(selectinload(StoreDailyRecord.items))
            .order_by(StoreDailyRecord.date.desc(), StoreDailyRecord.id.desc())
        )
        return list(records)

    async def form_config(self, *, store: Store, record_date: date) -> dict[str, Any]:
        record = await self._find_record(store_id=store.id, record_date=record_date)
        if record is not None:
            return {
                "store_id": store.id,
                "enabled": record.income_mode == "composed",
                "items": [
                    {
                        "category_id": item.category_id,
                        "name": item.category_name,
                        "include_in_total": item.include_in_total,
                        "is_active": True,
                        "sort_order": item.sort_order,
                    }
                    for item in sorted(
                        record.items, key=lambda item: (item.sort_order, item.id)
                    )
                ],
            }
        categories = list(
            await self.session.scalars(
                select(IncomeCategory)
                .where(
                    IncomeCategory.store_id == store.id,
                    IncomeCategory.archived_at.is_(None),
                )
                .order_by(IncomeCategory.sort_order, IncomeCategory.id)
            )
        )
        return {
            "store_id": store.id,
            "enabled": store.income_items_enabled,
            "items": [
                {
                    "category_id": item.id,
                    "name": item.name,
                    "include_in_total": item.include_in_total,
                    "is_active": item.is_active,
                    "sort_order": item.sort_order,
                }
                for item in categories
            ],
        }

    @staticmethod
    def _amount(value: Any, *, field: str, rest_day: bool) -> int:
        if type(value) is not int or not 0 <= value <= _MAX_MONEY:
            raise HTTPException(
                422, f"{field} must be an integer between 0 and {_MAX_MONEY}"
            )
        return 0 if rest_day else value

    async def _upsert_locked(
        self,
        *,
        store: Store,
        record_date: date,
        payload: dict[str, Any],
        actor_id: int,
    ) -> tuple[bool, int, date]:
        record = await self._find_record(store_id=store.id, record_date=record_date)
        created = record is None
        income_mode = (
            "composed" if store.income_items_enabled else "legacy_total"
        ) if record is None else record.income_mode
        rest_day = payload["is_open"] == "休息"
        items = payload.get("items", [])
        category_ids = [item["category_id"] for item in items]
        if len(category_ids) != len(set(category_ids)):
            raise HTTPException(422, "Duplicate income categories are not allowed")

        snapshots: dict[int, tuple[str, bool, int]] = {}
        item_values: list[tuple[int, int]] = []
        if income_mode == "legacy_total":
            if items:
                raise HTTPException(422, "Total revenue mode does not accept income items")
            if payload.get("daily_revenue") is None:
                raise HTTPException(422, "Daily revenue is required")
            daily_revenue = self._amount(
                payload["daily_revenue"], field="Daily revenue", rest_day=rest_day
            )
        else:
            if payload.get("daily_revenue") is not None:
                raise HTTPException(422, "Composed revenue mode does not accept daily revenue")
            if record is None:
                categories = list(
                    await self.session.scalars(
                        select(IncomeCategory)
                        .where(
                            IncomeCategory.store_id == store.id,
                            IncomeCategory.archived_at.is_(None),
                            IncomeCategory.is_active.is_(True),
                        )
                        .order_by(IncomeCategory.sort_order, IncomeCategory.id)
                        .execution_options(populate_existing=True)
                    )
                )
                snapshots = {
                    category.id: (
                        category.name,
                        category.include_in_total,
                        category.sort_order,
                    )
                    for category in categories
                }
            else:
                snapshots = {
                    item.category_id: (
                        item.category_name,
                        item.include_in_total,
                        item.sort_order,
                    )
                    for item in record.items
                }
            if set(category_ids) != set(snapshots) or len(items) != len(snapshots):
                raise HTTPException(
                    422, "Every active income item must be provided exactly once"
                )
            item_values = [
                (
                    item["category_id"],
                    self._amount(
                        item["amount"], field="Income amount", rest_day=rest_day
                    ),
                )
                for item in items
            ]
            daily_revenue = sum(
                amount
                for category_id, amount in item_values
                if snapshots[category_id][1]
            )
            if daily_revenue > _MAX_MONEY:
                raise HTTPException(422, "Daily revenue exceeds integer capacity")

        if record is None:
            record = StoreDailyRecord(
                store_id=store.id,
                date=record_date,
                created_by=actor_id,
                updated_by=actor_id,
                income_mode=income_mode,
            )
            self.session.add(record)
        else:
            record.updated_by = actor_id
            record.items.clear()
            await self.session.flush()

        record.is_open = payload["is_open"]
        record.daily_revenue = daily_revenue
        record.wash_count = 0 if rest_day else payload.get("wash_count")
        record.weather = payload.get("weather")
        record.weather_edited = payload.get("weather_edited", False)
        for field in (
            "weather_auto",
            "weather_code",
            "temperature_max",
            "temperature_min",
            "precipitation",
        ):
            if field in payload:
                setattr(record, field, payload[field])
        if not record.weather_edited and not record.weather and record.weather_auto:
            record.weather = record.weather_auto
        record.activity = payload.get("activity")
        if "scanned" in payload:
            record.scanned = bool(payload["scanned"])
        record.items = [
            DailyIncomeItem(
                category_id=category_id,
                category_name=snapshots[category_id][0],
                include_in_total=snapshots[category_id][1],
                sort_order=snapshots[category_id][2],
                amount=amount,
            )
            for category_id, amount in item_values
        ]
        await self.session.commit()
        return created, record.id, record.date

    async def upsert(
        self,
        *,
        store: Store,
        record_date: date,
        payload: dict[str, Any],
        actor: User,
    ) -> LedgerWriteResult:
        if record_date > self._local_today(store):
            raise HTTPException(422, "Future ledger dates are not allowed")
        store_id = store.id
        actor_id = actor.id
        async with SQLITE_WRITE_LOCK:
            try:
                # The dependency-loaded Store may predate weather or another external wait.
                # End that read transaction only after winning the process write lock, then
                # reload the configuration used to choose a new record's immutable mode.
                await self.session.commit()
                fresh_store = await self.session.scalar(
                    select(Store)
                    .where(Store.id == store_id)
                    .execution_options(populate_existing=True)
                )
                if fresh_store is None:
                    raise HTTPException(404, "Store not found")
                created, record_id, canonical_date = await self._upsert_locked(
                    store=fresh_store,
                    record_date=record_date,
                    payload=payload,
                    actor_id=actor_id,
                )
            except Exception:
                await self.session.rollback()
                raise
        canonical = await self._find_record(
            store_id=store.id, record_date=record_date
        )
        assert canonical is not None
        return LedgerWriteResult(
            record=canonical,
            created=created,
            event=LedgerChanged(
                store_id=store.id,
                record_id=record_id,
                record_date=canonical_date,
                operation="created" if created else "updated",
                actor_id=actor_id,
            ),
        )

    async def delete(
        self,
        *,
        store: Store,
        record_date: date,
        actor: User,
    ) -> LedgerChanged:
        async with SQLITE_WRITE_LOCK:
            try:
                record = await self._find_record(
                    store_id=store.id, record_date=record_date
                )
                if record is None:
                    raise HTTPException(404, "Record not found")
                event = LedgerChanged(
                    store_id=store.id,
                    record_id=record.id,
                    record_date=record.date,
                    operation="deleted",
                    actor_id=actor.id,
                )
                await self.session.delete(record)
                await self.session.commit()
                return event
            except Exception:
                await self.session.rollback()
                raise
