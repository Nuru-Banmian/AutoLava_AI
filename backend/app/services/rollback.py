from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager
from sqlalchemy.orm.attributes import flag_modified

from app.models.audit import AuditLog
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.audit import record_snapshot


class RollbackService:
    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _not_restorable() -> HTTPException:
        return HTTPException(409, "Audit snapshot is not restorable")

    async def _lock_audit(self, audit_id: int) -> AuditLog:
        audit = await self.session.scalar(
            select(AuditLog)
            .where(AuditLog.id == audit_id, AuditLog.operation_domain == "ledger")
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if audit is None:
            raise HTTPException(404, "Audit entry not found")
        return audit

    async def _lock_record(self, audit: AuditLog) -> StoreDailyRecord | None:
        if audit.store_id is None or audit.record_date is None:
            raise self._not_restorable()
        result = await self.session.execute(
            select(StoreDailyRecord)
            .outerjoin(
                DailyIncomeItem,
                DailyIncomeItem.record_id == StoreDailyRecord.id,
            )
            .options(contains_eager(StoreDailyRecord.items))
            .where(
                StoreDailyRecord.store_id == audit.store_id,
                StoreDailyRecord.date == audit.record_date,
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.unique().scalar_one_or_none()

    @staticmethod
    def _is_duplicate_rollback(exc: IntegrityError) -> bool:
        original_args = getattr(exc.orig, "args", ())
        return bool(
            original_args
            and original_args[0] == 1062
            and "uq_audit_log_rollback_of_audit_id" in str(exc.orig)
        )

    async def _reserve_rollback(self, audit: AuditLog, actor_id: int) -> AuditLog:
        rollback_audit = AuditLog(
            operation_domain="ledger",
            store_id=audit.store_id,
            record_id=audit.record_id,
            record_date=audit.record_date,
            operation_type="rollback",
            operation_source="manual",
            operator_user_id=actor_id,
            before_json=None,
            after_json=None,
            description=f"Rollback audit {audit.id}",
            requires_approval=False,
            approved=True,
            rollback_of_audit_id=audit.id,
        )
        try:
            async with self.session.begin_nested():
                self.session.add(rollback_audit)
                await self.session.flush()
        except IntegrityError as exc:
            if self._is_duplicate_rollback(exc):
                raise HTTPException(409, "Audit entry already rolled back") from exc
            raise
        return rollback_audit

    async def _validate_target(self, audit: AuditLog, target: dict[str, Any]) -> None:
        try:
            target_date = date.fromisoformat(target["date"])
            target_id = int(target["id"])
            target_store_id = int(target["store_id"])
            items = target["items"]
            item_ids = [int(item["id"]) for item in items]
            category_ids = [int(item["category_id"]) for item in items]
            self._decimal(target["daily_revenue"])
            for name in ("temperature_max", "temperature_min", "precipitation"):
                self._optional_decimal(target[name])
            datetime.fromisoformat(target["created_at"])
            datetime.fromisoformat(target["updated_at"])
            for item in items:
                self._decimal(item["amount"])
                datetime.fromisoformat(item["created_at"])
                datetime.fromisoformat(item["updated_at"])
        except (KeyError, TypeError, ValueError, InvalidOperation) as exc:
            raise self._not_restorable() from exc
        if (
            audit.store_id != target_store_id
            or audit.record_date != target_date
            or audit.record_id != target_id
            or len(item_ids) != len(set(item_ids))
            or len(category_ids) != len(set(category_ids))
        ):
            raise self._not_restorable()
        if category_ids:
            found = set(
                await self.session.scalars(
                    select(IncomeCategory.id).where(
                        IncomeCategory.store_id == target_store_id,
                        IncomeCategory.id.in_(category_ids),
                    )
                )
            )
            if found != set(category_ids):
                raise self._not_restorable()

    @staticmethod
    def _decimal(value: Any) -> Decimal:
        result = Decimal(str(value))
        if not result.is_finite():
            raise InvalidOperation
        return result

    @classmethod
    def _optional_decimal(cls, value: Any) -> Decimal | None:
        return None if value is None else cls._decimal(value)

    @classmethod
    def _apply_record_snapshot(cls, record: StoreDailyRecord, target: dict[str, Any]) -> None:
        record.store_id = int(target["store_id"])
        record.date = date.fromisoformat(target["date"])
        record.daily_revenue = cls._decimal(target["daily_revenue"])
        record.wash_count = target["wash_count"]
        record.is_open = target["is_open"]
        record.weather = target["weather"]
        record.weather_auto = target["weather_auto"]
        record.weather_code = target["weather_code"]
        record.temperature_max = cls._optional_decimal(target["temperature_max"])
        record.temperature_min = cls._optional_decimal(target["temperature_min"])
        record.precipitation = cls._optional_decimal(target["precipitation"])
        record.activity = target["activity"]
        record.weather_edited = target["weather_edited"]
        record.scanned = target["scanned"]
        record.created_by = int(target["created_by"])
        record.updated_by = int(target["updated_by"])
        record.created_at = datetime.fromisoformat(target["created_at"])
        record.updated_at = datetime.fromisoformat(target["updated_at"])

    @classmethod
    def _snapshot_items(cls, target: dict[str, Any]) -> list[DailyIncomeItem]:
        return [
            DailyIncomeItem(
                id=int(item["id"]),
                category_id=int(item["category_id"]),
                amount=cls._decimal(item["amount"]),
                created_at=datetime.fromisoformat(item["created_at"]),
                updated_at=datetime.fromisoformat(item["updated_at"]),
            )
            for item in target["items"]
        ]

    async def _restore_snapshot(
        self,
        current: StoreDailyRecord | None,
        target: dict[str, Any],
    ) -> StoreDailyRecord:
        if current is None:
            current = StoreDailyRecord(id=int(target["id"]))
            self._apply_record_snapshot(current, target)
            current.items = self._snapshot_items(target)
            self.session.add(current)
        else:
            current.items.clear()
            await self.session.flush()
            self._apply_record_snapshot(current, target)
            flag_modified(current, "updated_at")
            current.items = self._snapshot_items(target)
        await self.session.flush()
        await self.session.refresh(
            current,
            attribute_names=["daily_revenue", "created_at", "updated_at", "items"],
        )
        return current

    async def rollback(self, audit_id: int, actor_id: int) -> StoreDailyRecord | None:
        try:
            audit = await self._lock_audit(audit_id)
            rollback_audit = await self._reserve_rollback(audit, actor_id)

            current = await self._lock_record(audit)
            current_snapshot = None if current is None else record_snapshot(current)
            if current_snapshot != audit.after_json:
                raise HTTPException(409, "Record changed after this audit entry")

            target = audit.before_json
            if target is not None:
                await self._validate_target(audit, target)

            async with self.session.begin_nested():
                if target is None:
                    restored = None
                    if current is not None:
                        await self.session.delete(current)
                        await self.session.flush()
                else:
                    restored = await self._restore_snapshot(current, target)

                restored_snapshot = None if restored is None else record_snapshot(restored)
                if restored_snapshot != target:
                    raise self._not_restorable()
                rollback_audit.before_json = current_snapshot
                rollback_audit.after_json = restored_snapshot
                await self.session.flush()
            await self.session.commit()
            return restored
        except HTTPException:
            await self.session.rollback()
            raise
        except IntegrityError as exc:
            await self.session.rollback()
            raise self._not_restorable() from exc
        except Exception:
            await self.session.rollback()
            raise
