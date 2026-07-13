from typing import Any

from app.models.audit import AuditLog
from app.models.ledger import StoreDailyRecord


def record_snapshot(record: StoreDailyRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "store_id": record.store_id,
        "date": record.date.isoformat(),
        "daily_revenue": str(record.daily_revenue),
        "wash_count": record.wash_count,
        "is_open": record.is_open,
        "weather": record.weather,
        "weather_auto": record.weather_auto,
        "weather_code": record.weather_code,
        "temperature_max": (
            None if record.temperature_max is None else str(record.temperature_max)
        ),
        "temperature_min": (
            None if record.temperature_min is None else str(record.temperature_min)
        ),
        "precipitation": None if record.precipitation is None else str(record.precipitation),
        "activity": record.activity,
        "weather_edited": record.weather_edited,
        "scanned": record.scanned,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "created_at": record.created_at.isoformat(),
        "updated_at": record.updated_at.isoformat(),
        "items": [
            {
                "id": item.id,
                "category_id": item.category_id,
                "amount": str(item.amount),
                "created_at": item.created_at.isoformat(),
                "updated_at": item.updated_at.isoformat(),
            }
            for item in sorted(record.items, key=lambda value: value.category_id)
        ],
    }


def make_ledger_audit(
    *,
    record: StoreDailyRecord,
    operation_type: str,
    source: str,
    user_id: int,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
    requires_approval: bool = False,
    approved: bool = True,
) -> AuditLog:
    return AuditLog(
        operation_domain="ledger",
        store_id=record.store_id,
        record_id=record.id,
        record_date=record.date,
        operation_type=operation_type,
        operation_source=source,
        operator_user_id=user_id,
        before_json=before,
        after_json=after,
        description=f"Ledger {operation_type} for {record.date.isoformat()}",
        requires_approval=requires_approval,
        approved=approved,
    )


def add_admin_audit(
    session,
    *,
    actor_id: int,
    store_id: int | None,
    record_id: int | None,
    operation_type: str,
    description: str,
    before: dict[str, Any] | None,
    after: dict[str, Any] | None,
) -> AuditLog:
    entry = AuditLog(
        operation_domain="admin",
        store_id=store_id,
        record_id=record_id,
        record_date=None,
        operation_type=operation_type,
        operation_source="manual",
        operator_user_id=actor_id,
        before_json=before,
        after_json=after,
        description=description,
        requires_approval=False,
        approved=True,
    )
    session.add(entry)
    return entry
