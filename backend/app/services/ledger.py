from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, selectinload

from app.models.identity import Store, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.audit import make_ledger_audit, record_snapshot

_MONEY_QUANTUM = Decimal("0.01")
_MONEY_MAX = Decimal("9999999999.99")


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
    ) -> tuple[StoreDailyRecord, bool]:
        if record_date > self._local_today(store):
            raise HTTPException(422, "Future ledger dates are not allowed")

        record = await self._find_record(
            store_id=store.id, record_date=record_date, for_update=True
        )
        created = record is None
        if record is not None and not overwrite:
            raise HTTPException(409, "Record exists; confirm overwrite")

        items = payload["items"]
        category_id_list = [item["category_id"] for item in items]
        category_ids = set(category_id_list)
        if len(category_id_list) != len(category_ids):
            raise HTTPException(422, "Duplicate income categories are not allowed")

        categories = await self._categories_for(store_id=store.id, category_ids=category_ids)
        if set(categories) != category_ids:
            raise HTTPException(422, "Income category does not belong to this store")
        previous_category_ids = (
            set() if record is None else {item.category_id for item in record.items}
        )
        if any(
            not category.is_active and category.id not in previous_category_ids
            for category in categories.values()
        ):
            raise HTTPException(
                422, "Inactive categories may only be retained on historical records"
            )

        rest_day = payload["is_open"] == "休息"
        item_values = self._item_values(items, rest_day=rest_day)
        daily_revenue = Decimal("0.00")
        for category_id, amount in item_values:
            if categories[category_id].include_in_total:
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
                    )
                    self.session.add(record)
                else:
                    record.updated_by = actor.id
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
                        category_name=categories[category_id].name,
                        include_in_total=categories[category_id].include_in_total,
                        sort_order=categories[category_id].sort_order,
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
        return record, created

    async def delete(
        self,
        *,
        store: Store,
        record_date: date,
        actor: User,
        source: str = "manual",
        requires_approval: bool = False,
        approved: bool = True,
    ) -> None:
        record = await self._find_record(
            store_id=store.id, record_date=record_date, for_update=True
        )
        if record is None:
            raise HTTPException(404, "Record not found")
        before = record_snapshot(record)
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
