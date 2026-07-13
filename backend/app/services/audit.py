from typing import Any

from app.models.audit import AuditLog


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
