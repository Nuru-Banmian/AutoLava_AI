from datetime import date, datetime, timedelta
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, selectinload

from app.models.identity import Store, User
from app.events.ledger import LedgerChanged
from app.models.income_config import IncomeConfigVersion
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.audit import make_ledger_audit, record_snapshot

_MONEY_QUANTUM = Decimal("0.01")
_MONEY_MAX = Decimal("9999999999.99")


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
        self, *, store_id: int, record_date: date, for_update: bool = False
    ) -> StoreDailyRecord | None:
        if for_update:
            result = await self.session.execute(
                select(StoreDailyRecord)
                .outerjoin(
                    DailyIncomeItem,
                    DailyIncomeItem.record_id == StoreDailyRecord.id,
                )
                .where(
                    StoreDailyRecord.store_id == store_id,
                    StoreDailyRecord.date == record_date,
                )
                .options(contains_eager(StoreDailyRecord.items))
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            return result.unique().scalar_one_or_none()
        statement = (
            select(StoreDailyRecord)
            .where(
                StoreDailyRecord.store_id == store_id,
                StoreDailyRecord.date == record_date,
            )
            .options(selectinload(StoreDailyRecord.items))
            .execution_options(populate_existing=True)
        )
        return await self.session.scalar(statement)

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
            version_number = 0
            if record.income_config_version_id is not None:
                version_number = (
                    await self.session.scalar(
                        select(IncomeConfigVersion.version).where(
                            IncomeConfigVersion.id == record.income_config_version_id
                        )
                    )
                    or 0
                )
            return {
                "store_id": store.id,
                "enabled": record.income_mode == "composed",
                "version_id": record.income_config_version_id,
                "version": version_number,
                "items": [
                    {
                        "category_id": item.category_id,
                        "name": item.category_name,
                        "include_in_total": item.include_in_total,
                        "is_active": True,
                        "sort_order": item.sort_order,
                    }
                    for item in sorted(record.items, key=lambda item: (item.sort_order, item.id))
                ],
            }
        config = await self.session.scalar(
            select(IncomeConfigVersion)
            .where(IncomeConfigVersion.store_id == store.id)
            .options(selectinload(IncomeConfigVersion.items))
            .order_by(IncomeConfigVersion.version.desc())
            .limit(1)
        )
        return {
            "store_id": store.id,
            "enabled": config is not None and config.enabled,
            "version_id": None if config is None else config.id,
            "version": 0 if config is None else config.version,
            "items": []
            if config is None
            else [
                {
                    "category_id": item.category_id,
                    "name": item.name,
                    "include_in_total": item.include_in_total,
                    "is_active": item.is_active,
                    "sort_order": item.sort_order,
                }
                for item in sorted(config.items, key=lambda item: (item.sort_order, item.id))
            ],
        }

    async def _categories_for(
        self, *, store_id: int, category_ids: set[int]
    ) -> dict[int, IncomeCategory]:
        if not category_ids:
            return {}
        categories = await self.session.scalars(
            select(IncomeCategory)
            .where(
                IncomeCategory.store_id == store_id,
                IncomeCategory.id.in_(category_ids),
            )
            .with_for_update()
        )
        return {category.id: category for category in categories}

    @staticmethod
    def _item_values(items: list[dict[str, Any]], *, rest_day: bool) -> list[tuple[int, Decimal]]:
        values: list[tuple[int, Decimal]] = []
        for item in items:
            try:
                amount = Decimal(str(item["amount"]))
            except (InvalidOperation, TypeError, ValueError) as exc:
                raise HTTPException(422, "Income amount must be a finite decimal") from exc
            if not amount.is_finite():
                raise HTTPException(422, "Income amount must be a finite decimal")
            if amount < 0:
                raise HTTPException(422, "Income amounts must be non-negative")
            if amount > _MONEY_MAX:
                raise HTTPException(422, "Income amount exceeds NUMERIC(12,2) capacity")
            canonical_amount = amount.quantize(_MONEY_QUANTUM)
            if canonical_amount != amount:
                raise HTTPException(422, "Income amounts must have at most two decimal places")
            values.append((item["category_id"], Decimal("0.00") if rest_day else canonical_amount))
        return values

    @staticmethod
    def _direct_total(value: Any, *, rest_day: bool) -> Decimal:
        try:
            amount = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as exc:
            raise HTTPException(422, "Daily revenue must be a finite decimal") from exc
        if not amount.is_finite() or amount < 0:
            raise HTTPException(422, "Daily revenue must be non-negative")
        if amount > _MONEY_MAX:
            raise HTTPException(422, "Daily revenue exceeds NUMERIC(12,2) capacity")
        canonical = amount.quantize(_MONEY_QUANTUM)
        if canonical != amount:
            raise HTTPException(422, "Daily revenue must have at most two decimal places")
        return Decimal("0.00") if rest_day else canonical

    async def upsert(
        self,
        *,
        store: Store,
        record_date: date,
        payload: dict[str, Any],
        actor: User,
        overwrite: bool = False,
        source: str = "manual",
        requires_approval: bool = False,
        approved: bool = True,
    ) -> LedgerWriteResult:
        if record_date > self._local_today(store):
            raise HTTPException(422, "Future ledger dates are not allowed")

        record = await self._find_record(
            store_id=store.id, record_date=record_date, for_update=True
        )
        created = record is None
        if record is not None and not overwrite:
            raise HTTPException(409, "Record exists; confirm overwrite")
        if record is not None and payload.get("expected_version") != record.row_version:
            raise HTTPException(409, "Record changed; reload before saving")

        items = payload.get("items", [])
        category_id_list = [item["category_id"] for item in items]
        category_ids = set(category_id_list)
        if len(category_id_list) != len(category_ids):
            raise HTTPException(422, "Duplicate income categories are not allowed")

        rest_day = payload["is_open"] == "休息"
        config: IncomeConfigVersion | None = None
        if record is None:
            config = await self.session.scalar(
                select(IncomeConfigVersion)
                .where(IncomeConfigVersion.store_id == store.id)
                .options(selectinload(IncomeConfigVersion.items))
                .order_by(IncomeConfigVersion.version.desc())
                .limit(1)
            )
            income_mode = "composed" if config is not None and config.enabled else "legacy_total"
        else:
            income_mode = record.income_mode

        snapshot_values: dict[int, tuple[str, bool, int]] = {}
        if income_mode == "legacy_total":
            if items:
                raise HTTPException(422, "Total revenue mode does not accept income items")
            if payload.get("daily_revenue") is None:
                raise HTTPException(422, "Daily revenue is required")
            item_values: list[tuple[int, Decimal]] = []
            daily_revenue = self._direct_total(payload["daily_revenue"], rest_day=rest_day)
        else:
            if payload.get("daily_revenue") is not None:
                raise HTTPException(422, "Composed revenue mode does not accept daily revenue")
            bound_version_id = (
                config.id if record is None and config is not None else record.income_config_version_id
            )
            if payload.get("config_version_id") != bound_version_id:
                raise HTTPException(409, "Income configuration version does not match")
            if record is None:
                if config is None:
                    raise HTTPException(409, "Income configuration version does not match")
                expected = [item for item in config.items if item.is_active]
                snapshot_values = {
                    item.category_id: (item.name, item.include_in_total, item.sort_order)
                    for item in expected
                    if item.category_id is not None
                }
            else:
                snapshot_values = {
                    item.category_id: (
                        item.category_name,
                        item.include_in_total,
                        item.sort_order,
                    )
                    for item in record.items
                }
            if category_ids != set(snapshot_values) or len(items) != len(snapshot_values):
                raise HTTPException(422, "Every active income item must be provided exactly once")
            item_values = self._item_values(items, rest_day=rest_day)
            daily_revenue = Decimal("0.00")
            for category_id, amount in item_values:
                if snapshot_values[category_id][1]:
                    daily_revenue += amount
                    if daily_revenue > _MONEY_MAX:
                        raise HTTPException(422, "Daily revenue exceeds NUMERIC(12,2) capacity")
        before = None if record is None else record_snapshot(record)

        try:
            async with self.session.begin_nested():
                if record is None:
                    record = StoreDailyRecord(
                        store_id=store.id,
                        date=record_date,
                        created_by=actor.id,
                        updated_by=actor.id,
                        income_mode=income_mode,
                        income_config_version_id=None if config is None else config.id,
                    )
                    self.session.add(record)
                else:
                    record.updated_by = actor.id
                    record.row_version += 1
                    record.items.clear()
                    await self.session.flush()

                record.is_open = payload["is_open"]
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
                        category_name=snapshot_values[category_id][0],
                        include_in_total=snapshot_values[category_id][1],
                        sort_order=snapshot_values[category_id][2],
                        amount=amount,
                    )
                    for category_id, amount in item_values
                ]
                record.daily_revenue = daily_revenue
                await self.session.flush()
                await self.session.refresh(
                    record,
                    attribute_names=["daily_revenue", "created_at", "updated_at", "items"],
                )
                after = record_snapshot(record)
                self.session.add(
                    make_ledger_audit(
                        record=record,
                        operation_type="create" if created else "update",
                        source=source,
                        user_id=actor.id,
                        before=before,
                        after=after,
                        requires_approval=requires_approval,
                        approved=approved,
                    )
                )
                await self.session.flush()
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise HTTPException(409, "Record exists; confirm overwrite") from exc
        except Exception:
            await self.session.rollback()
            raise
        return LedgerWriteResult(
            record=record,
            created=created,
            event=LedgerChanged(
                store_id=store.id,
                record_id=record.id,
                record_date=record.date,
                operation="created" if created else "updated",
                actor_id=actor.id,
                row_version=record.row_version,
            ),
        )

    async def delete(
        self,
        *,
        store: Store,
        record_date: date,
        actor: User,
        expected_version: int,
        source: str = "manual",
        requires_approval: bool = False,
        approved: bool = True,
    ) -> LedgerChanged:
        record = await self._find_record(
            store_id=store.id, record_date=record_date, for_update=True
        )
        if record is None:
            raise HTTPException(404, "Record not found")
        if record.row_version != expected_version:
            raise HTTPException(409, "Record changed; reload before saving")
        before = record_snapshot(record)
        event = LedgerChanged(
            store_id=store.id,
            record_id=record.id,
            record_date=record.date,
            operation="deleted",
            actor_id=actor.id,
            row_version=None,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(
                    make_ledger_audit(
                        record=record,
                        operation_type="delete",
                        source=source,
                        user_id=actor.id,
                        before=before,
                        after=None,
                        requires_approval=requires_approval,
                        approved=approved,
                    )
                )
                await self.session.delete(record)
                await self.session.flush()
            await self.session.commit()
        except Exception:
            await self.session.rollback()
            raise
        return event
