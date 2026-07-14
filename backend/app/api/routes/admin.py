from collections.abc import Iterable
from datetime import date
from decimal import Decimal
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Session, require_admin
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.identity import Store, StoreMember, StoreSetting, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import ScheduledTaskLog, SystemAlert
from app.schemas.admin import (
    CategoryCreate,
    CategoryPatch,
    MemberReplace,
    StoreCreate,
    StorePatch,
    UserCreate,
    UserPatch,
)
from app.services.audit import add_admin_audit

router = APIRouter(prefix="/admin", tags=["admin"], dependencies=[Depends(require_admin)])
AdminUser = Annotated[User, Depends(require_admin)]


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _date(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
    }


def _user_snapshot(user: User, *, password_changed: bool = False) -> dict[str, Any]:
    snapshot = _user_payload(user)
    if password_changed:
        snapshot["password_changed"] = True
    return snapshot


def _store_payload(store: Store) -> dict[str, Any]:
    return {
        "id": store.id,
        "name": store.name,
        "address": store.address,
        "latitude": _decimal(store.latitude),
        "longitude": _decimal(store.longitude),
        "timezone": store.timezone,
        "is_active": store.is_active,
    }


def _category_payload(category: IncomeCategory) -> dict[str, Any]:
    return {
        "id": category.id,
        "store_id": category.store_id,
        "name": category.name,
        "include_in_total": category.include_in_total,
        "is_active": category.is_active,
        "sort_order": category.sort_order,
    }


def _item_snapshot(item: DailyIncomeItem) -> dict[str, Any]:
    return {
        "id": item.id,
        "category_id": item.category_id,
        "amount": _decimal(item.amount),
    }


def _record_snapshot(record: StoreDailyRecord) -> dict[str, Any]:
    return {
        "id": record.id,
        "store_id": record.store_id,
        "date": record.date.isoformat(),
        "daily_revenue": _decimal(record.daily_revenue),
        "wash_count": record.wash_count,
        "is_open": record.is_open,
        "weather": record.weather,
        "weather_auto": record.weather_auto,
        "weather_code": record.weather_code,
        "temperature_max": _decimal(record.temperature_max),
        "temperature_min": _decimal(record.temperature_min),
        "precipitation": _decimal(record.precipitation),
        "activity": record.activity,
        "weather_edited": record.weather_edited,
        "scanned": record.scanned,
        "created_by": record.created_by,
        "updated_by": record.updated_by,
        "items": [_item_snapshot(item) for item in sorted(record.items, key=lambda item: item.id)],
    }


def _audit_payload(audit: AuditLog) -> dict[str, Any]:
    return {
        "id": audit.id,
        "operation_domain": audit.operation_domain,
        "store_id": audit.store_id,
        "record_id": audit.record_id,
        "record_date": _date(audit.record_date),
        "operation_type": audit.operation_type,
        "operation_source": audit.operation_source,
        "before": audit.before_json,
        "after": audit.after_json,
        "description": audit.description,
        "approved": audit.approved,
        "created_at": audit.created_at,
    }


def _alert_payload(alert: SystemAlert) -> dict[str, Any]:
    return {
        "id": alert.id,
        "store_id": alert.store_id,
        "alert_type": alert.alert_type,
        "level": alert.level,
        "message": alert.message,
        "is_resolved": alert.is_resolved,
        "created_at": alert.created_at,
        "resolved_at": alert.resolved_at,
    }


def _task_log_payload(task_log: ScheduledTaskLog) -> dict[str, Any]:
    return {
        "id": task_log.id,
        "store_id": task_log.store_id,
        "task_type": task_log.task_type,
        "status": task_log.status,
        "message": task_log.message,
        "retry_count": task_log.retry_count,
        "started_at": task_log.started_at,
        "finished_at": task_log.finished_at,
        "created_at": task_log.created_at,
    }


def _add_ledger_recalculation_audit(
    session,
    *,
    actor_id: int,
    record: StoreDailyRecord,
    before: dict[str, Any],
    after: dict[str, Any],
) -> None:
    session.add(
        AuditLog(
            operation_domain="ledger",
            store_id=record.store_id,
            record_id=record.id,
            record_date=record.date,
            operation_type="update",
            operation_source="system",
            operator_user_id=actor_id,
            before_json=before,
            after_json=after,
            description="Recomputed daily revenue after income category configuration change",
            requires_approval=False,
            approved=True,
        )
    )


async def _require_store(session: Session, store_id: int) -> Store:
    store = await session.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Store not found")
    return store


async def _require_users(session: Session, user_ids: Iterable[int]) -> None:
    unique_ids = sorted(set(user_ids))
    if not unique_ids:
        return
    found_ids = set(await session.scalars(select(User.id).where(User.id.in_(unique_ids))))
    if found_ids != set(unique_ids):
        raise HTTPException(404, "User not found")


@router.get("/users")
async def list_users(session: Session) -> list[dict[str, Any]]:
    users = (await session.scalars(select(User).order_by(User.username, User.id))).all()
    return [_user_payload(user) for user in users]


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, session: Session, actor: AdminUser) -> dict[str, Any]:
    user = User(
        username=body.username,
        password_hash=hash_password(body.password),
        role=body.role,
    )
    try:
        async with session.begin_nested():
            session.add(user)
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "Username already exists") from exc
    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=None,
        record_id=user.id,
        operation_type="create",
        description=f"Created user {user.username}",
        before=None,
        after=_user_snapshot(user, password_changed=True),
    )
    await session.commit()
    return _user_payload(user)


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int, body: UserPatch, session: Session, actor: AdminUser
) -> dict[str, Any]:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(404, "User not found")
    password_changed = body.password is not None
    before = _user_snapshot(user, password_changed=password_changed)
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.is_active is not None:
        user.is_active = body.is_active
    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=None,
        record_id=user.id,
        operation_type="update",
        description=f"Updated user {user.username}",
        before=before,
        after=_user_snapshot(user, password_changed=password_changed),
    )
    await session.commit()
    return _user_payload(user)


@router.get("/users/{user_id}/stores")
async def list_user_stores(user_id: int, session: Session) -> list[dict[str, Any]]:
    if await session.get(User, user_id) is None:
        raise HTTPException(404, "User not found")
    stores = (
        await session.scalars(
            select(Store)
            .join(StoreMember, StoreMember.store_id == Store.id)
            .where(StoreMember.user_id == user_id)
            .order_by(Store.name, Store.id)
        )
    ).all()
    return [_store_payload(store) for store in stores]


@router.get("/users/{user_id}/operations")
async def list_user_operations(user_id: int, session: Session) -> list[dict[str, Any]]:
    if await session.get(User, user_id) is None:
        raise HTTPException(404, "User not found")
    operations = (
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.operator_user_id == user_id)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
        )
    ).all()
    return [_audit_payload(operation) for operation in operations]


@router.get("/stores/geocode")
async def geocode_store(
    request: Request, query: Annotated[str, Query(min_length=1)]
) -> list[dict[str, str | float]]:
    return await request.app.state.open_meteo_provider.geocode(query)


@router.get("/stores")
async def list_stores(session: Session) -> list[dict[str, Any]]:
    stores = (await session.scalars(select(Store).order_by(Store.name, Store.id))).all()
    return [_store_payload(store) for store in stores]


@router.post("/stores", status_code=201)
async def create_store(body: StoreCreate, session: Session, actor: AdminUser) -> dict[str, Any]:
    store = Store(**body.model_dump())
    session.add(store)
    await session.flush()
    session.add(StoreSetting(store_id=store.id, standard_work_hours=8))
    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=store.id,
        record_id=store.id,
        operation_type="create",
        description=f"Created store {store.name}",
        before=None,
        after=_store_payload(store) | {"standard_work_hours": 8},
    )
    await session.commit()
    return _store_payload(store)


@router.patch("/stores/{store_id}")
async def patch_store(
    store_id: int, body: StorePatch, session: Session, actor: AdminUser
) -> dict[str, Any]:
    store = await _require_store(session, store_id)
    before = _store_payload(store)
    for field, value in body.model_dump(exclude_none=True).items():
        setattr(store, field, value)
    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=store.id,
        record_id=store.id,
        operation_type="update",
        description=f"Updated store {store.name}",
        before=before,
        after=_store_payload(store),
    )
    await session.commit()
    return _store_payload(store)


@router.get("/stores/{store_id}/members")
async def list_store_members(store_id: int, session: Session) -> list[dict[str, Any]]:
    await _require_store(session, store_id)
    users = (
        await session.scalars(
            select(User)
            .join(StoreMember, StoreMember.user_id == User.id)
            .where(StoreMember.store_id == store_id)
            .order_by(User.username, User.id)
        )
    ).all()
    return [_user_payload(user) for user in users]


@router.put("/stores/{store_id}/members")
async def replace_members(
    store_id: int, body: MemberReplace, session: Session, actor: AdminUser
) -> dict[str, Any]:
    await _require_store(session, store_id)
    user_ids = sorted(set(body.user_ids))
    await _require_users(session, user_ids)
    previous_ids = list(
        await session.scalars(
            select(StoreMember.user_id)
            .where(StoreMember.store_id == store_id)
            .order_by(StoreMember.user_id)
        )
    )
    await session.execute(delete(StoreMember).where(StoreMember.store_id == store_id))
    session.add_all(StoreMember(store_id=store_id, user_id=user_id) for user_id in user_ids)
    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=store_id,
        record_id=store_id,
        operation_type="update",
        description="Replaced store members",
        before={"store_id": store_id, "user_ids": previous_ids},
        after={"store_id": store_id, "user_ids": user_ids},
    )
    await session.commit()
    return {"store_id": store_id, "user_ids": user_ids}


@router.get("/income-categories")
async def list_income_categories(store_id: int, session: Session) -> list[dict[str, Any]]:
    await _require_store(session, store_id)
    categories = (
        await session.scalars(
            select(IncomeCategory)
            .where(IncomeCategory.store_id == store_id)
            .order_by(IncomeCategory.sort_order, IncomeCategory.id)
        )
    ).all()
    return [_category_payload(category) for category in categories]


@router.post("/income-categories", status_code=201)
async def create_income_category(
    body: CategoryCreate, session: Session, actor: AdminUser
) -> dict[str, Any]:
    await _require_store(session, body.store_id)
    category = IncomeCategory(**body.model_dump())
    session.add(category)
    await session.flush()
    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=category.store_id,
        record_id=category.id,
        operation_type="create",
        description=f"Created income category {category.name}",
        before=None,
        after=_category_payload(category),
    )
    await session.commit()
    return _category_payload(category)


@router.patch("/income-categories/{category_id}")
async def patch_income_category(
    category_id: int, body: CategoryPatch, session: Session, actor: AdminUser
) -> dict[str, Any]:
    category = await session.get(IncomeCategory, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    before_category = _category_payload(category)
    include_changed = (
        body.include_in_total is not None and body.include_in_total != category.include_in_total
    )
    records: list[StoreDailyRecord] = []
    before_records: dict[int, dict[str, Any]] = {}
    if include_changed:
        records = list(
            await session.scalars(
                select(StoreDailyRecord)
                .join(DailyIncomeItem, DailyIncomeItem.record_id == StoreDailyRecord.id)
                .where(DailyIncomeItem.category_id == category.id)
                .order_by(StoreDailyRecord.id)
                .with_for_update()
            )
        )
        before_records = {record.id: _record_snapshot(record) for record in records}

    for field, value in body.model_dump(exclude_none=True).items():
        setattr(category, field, value)

    if include_changed and records:
        await session.flush()
        totals = {record.id: Decimal("0.00") for record in records}
        included_amounts = await session.execute(
            select(DailyIncomeItem.record_id, DailyIncomeItem.amount)
            .join(IncomeCategory, IncomeCategory.id == DailyIncomeItem.category_id)
            .where(
                DailyIncomeItem.record_id.in_(totals),
                IncomeCategory.include_in_total.is_(True),
            )
        )
        for record_id, amount in included_amounts:
            totals[record_id] += amount
        for record in records:
            record.daily_revenue = totals[record.id]
            _add_ledger_recalculation_audit(
                session,
                actor_id=actor.id,
                record=record,
                before=before_records[record.id],
                after=_record_snapshot(record),
            )

    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=category.store_id,
        record_id=category.id,
        operation_type="update",
        description=f"Updated income category {category.name}",
        before=before_category,
        after=_category_payload(category),
    )
    await session.commit()
    return _category_payload(category)


@router.delete("/income-categories/{category_id}", status_code=204)
async def delete_unused_category(category_id: int, session: Session, actor: AdminUser) -> None:
    category = await session.get(IncomeCategory, category_id)
    if category is None:
        raise HTTPException(404, "Category not found")
    used = await session.scalar(
        select(DailyIncomeItem.id).where(DailyIncomeItem.category_id == category_id).limit(1)
    )
    if used is not None:
        raise HTTPException(409, "Used categories must be disabled")
    before = _category_payload(category)
    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=category.store_id,
        record_id=category.id,
        operation_type="delete",
        description=f"Deleted income category {category.name}",
        before=before,
        after=None,
    )
    await session.delete(category)
    await session.commit()


@router.get("/alerts")
async def list_alerts(session: Session) -> list[dict[str, Any]]:
    alerts = (
        await session.scalars(
            select(SystemAlert).order_by(SystemAlert.created_at.desc(), SystemAlert.id.desc())
        )
    ).all()
    return [_alert_payload(alert) for alert in alerts]


@router.get("/task-logs")
async def list_task_logs(session: Session) -> list[dict[str, Any]]:
    task_logs = (
        await session.scalars(
            select(ScheduledTaskLog).order_by(
                ScheduledTaskLog.created_at.desc(), ScheduledTaskLog.id.desc()
            )
        )
    ).all()
    return [_task_log_payload(task_log) for task_log in task_logs]
