from collections.abc import Iterable
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Session, require_capability
from app.core.security import hash_password
from app.models.audit import AuditLog
from app.models.identity import Store, StoreMember, StoreSetting, User
from app.models.income_config import IncomeConfigVersion
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import DailyBriefing, ScheduledTaskLog, SystemAlert
from app.schemas.admin import (
    CategoryCreate,
    CategoryPatch,
    MemberReplace,
    StoreCreate,
    StorePatch,
    UserCreate,
    UserPatch,
)
from app.schemas.time import timestamp_status, trusted_utc
from app.services.audit import add_admin_audit, record_snapshot
from app.services.briefing import BriefingService
from app.services.income_config import IncomeConfigService

router = APIRouter(prefix="/admin", tags=["admin"])
UsersManager = Annotated[User, Depends(require_capability("users.manage"))]
StoresManager = Annotated[User, Depends(require_capability("stores.manage"))]
IncomeConfigManager = Annotated[
    User, Depends(require_capability("income_config.manage"))
]


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


def _managed_user_payload(user: User, store_ids: list[int]) -> dict[str, Any]:
    return _user_payload(user) | {"store_ids": store_ids}


def _user_snapshot(
    user: User, *, password_changed: bool = False, store_ids: list[int] | None = None
) -> dict[str, Any]:
    snapshot = _user_payload(user)
    if store_ids is not None:
        snapshot["store_ids"] = store_ids
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
        "archived_at": category.archived_at,
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
        "rollbackable": audit.rollbackable,
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
        "created_at": trusted_utc(alert.created_at, alert.timestamp_contract),
        "resolved_at": trusted_utc(alert.resolved_at, alert.timestamp_contract),
        "timestamp_status": timestamp_status(alert.timestamp_contract),
    }


def _task_log_payload(task_log: ScheduledTaskLog) -> dict[str, Any]:
    return {
        "id": task_log.id,
        "store_id": task_log.store_id,
        "task_type": task_log.task_type,
        "status": task_log.status,
        "message": task_log.message,
        "retry_count": task_log.retry_count,
        "started_at": trusted_utc(task_log.started_at, task_log.timestamp_contract),
        "finished_at": trusted_utc(task_log.finished_at, task_log.timestamp_contract),
        "created_at": trusted_utc(task_log.created_at, task_log.timestamp_contract),
        "timestamp_status": timestamp_status(task_log.timestamp_contract),
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
            rollbackable=False,
        )
    )


async def _require_store(session: Session, store_id: int) -> Store:
    store = await session.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Store not found")
    return store


async def _require_users(session: Session, user_ids: Iterable[int]) -> list[User]:
    unique_ids = sorted(set(user_ids))
    if not unique_ids:
        return []
    users = list(
        await session.scalars(select(User).where(User.id.in_(unique_ids)).order_by(User.id))
    )
    if {user.id for user in users} != set(unique_ids):
        raise HTTPException(404, "User not found")
    return users


async def _require_stores(session: Session, store_ids: Iterable[int]) -> None:
    unique_ids = sorted(set(store_ids))
    if not unique_ids:
        return
    stores = list(await session.scalars(select(Store).where(Store.id.in_(unique_ids))))
    if {store.id for store in stores} != set(unique_ids):
        raise HTTPException(404, "Store not found")
    if any(not store.is_active for store in stores):
        raise HTTPException(409, "停用门店不能分配给用户")


async def _user_store_ids(session: Session, user_id: int) -> list[int]:
    return list(
        await session.scalars(
            select(StoreMember.store_id)
            .where(StoreMember.user_id == user_id)
            .order_by(StoreMember.store_id)
        )
    )


@router.get("/users", dependencies=[Depends(require_capability("users.manage"))])
async def list_users(session: Session) -> list[dict[str, Any]]:
    users = (await session.scalars(select(User).order_by(User.username, User.id))).all()
    memberships = await session.execute(
        select(StoreMember.user_id, StoreMember.store_id).order_by(
            StoreMember.user_id, StoreMember.store_id
        )
    )
    store_ids_by_user: dict[int, list[int]] = {}
    for user_id, store_id in memberships:
        store_ids_by_user.setdefault(user_id, []).append(store_id)
    return [
        _managed_user_payload(user, store_ids_by_user.get(user.id, [])) for user in users
    ]


@router.post("/users", status_code=201)
async def create_user(body: UserCreate, session: Session, actor: UsersManager) -> dict[str, Any]:
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
    return _managed_user_payload(user, [])


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int, body: UserPatch, session: Session, actor: UsersManager
) -> dict[str, Any]:
    active_admins: list[User] = []
    removes_active_admin = body.is_active is False or body.role == "user"
    if removes_active_admin:
        active_admins = list(
            await session.scalars(
                select(User)
                .where(User.role == "admin", User.is_active.is_(True))
                .order_by(User.id)
                .with_for_update()
                .execution_options(populate_existing=True)
            )
        )
    user = await session.scalar(
        select(User)
        .where(User.id == user_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if user is None:
        raise HTTPException(404, "User not found")
    if body.is_active is False and user.is_active:
        if user.id == actor.id:
            raise HTTPException(409, "You cannot deactivate your current account")
        if user.role == "admin" and len(active_admins) <= 1:
            raise HTTPException(409, "At least one active administrator is required")
    if body.role == "user" and user.role == "admin" and user.is_active:
        if len(active_admins) <= 1:
            raise HTTPException(409, "At least one active administrator is required")
    previous_store_ids = await _user_store_ids(session, user.id)
    password_changed = body.password is not None
    includes_access_change = body.role is not None or body.store_ids is not None
    before = _user_snapshot(
        user,
        password_changed=password_changed,
        store_ids=previous_store_ids if includes_access_change else None,
    )
    if body.password is not None:
        user.password_hash = hash_password(body.password)
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.role is not None:
        user.role = body.role
    next_store_ids = previous_store_ids
    if user.role == "admin":
        next_store_ids = []
    elif body.store_ids is not None:
        next_store_ids = sorted(set(body.store_ids))
        await _require_stores(session, next_store_ids)
    if includes_access_change:
        await session.execute(delete(StoreMember).where(StoreMember.user_id == user.id))
        session.add_all(
            StoreMember(store_id=store_id, user_id=user.id) for store_id in next_store_ids
        )
    add_admin_audit(
        session,
        actor_id=actor.id,
        store_id=None,
        record_id=user.id,
        operation_type="update",
        description=f"Updated user {user.username}",
        before=before,
        after=_user_snapshot(
            user,
            password_changed=password_changed,
            store_ids=next_store_ids if includes_access_change else None,
        ),
    )
    await session.commit()
    return _managed_user_payload(user, next_store_ids)


@router.delete("/users/{user_id}", status_code=204)
async def delete_unused_user(
    user_id: int, session: Session, actor: UsersManager
) -> None:
    user = await session.scalar(
        select(User).where(User.id == user_id).with_for_update()
    )
    if user is None:
        raise HTTPException(404, "User not found")
    if user.id == actor.id:
        raise HTTPException(409, "You cannot delete your current account")
    ledger_references = await session.scalar(
        select(func.count())
        .select_from(StoreDailyRecord)
        .where(
            (StoreDailyRecord.created_by == user.id)
            | (StoreDailyRecord.updated_by == user.id)
        )
    )
    audit_references = await session.scalar(
        select(func.count())
        .select_from(AuditLog)
        .where(AuditLog.operator_user_id == user.id)
    )
    config_references = await session.scalar(
        select(func.count())
        .select_from(IncomeConfigVersion)
        .where(IncomeConfigVersion.created_by == user.id)
    )
    if ledger_references or audit_references or config_references:
        raise HTTPException(409, "该用户已有历史记录，不能永久删除；请停用账号")
    await session.execute(delete(StoreMember).where(StoreMember.user_id == user.id))
    await session.delete(user)
    await session.commit()


@router.get(
    "/users/{user_id}/stores",
    dependencies=[Depends(require_capability("users.manage"))],
)
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


@router.get(
    "/users/{user_id}/operations",
    dependencies=[Depends(require_capability("audit.view"))],
)
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


@router.get(
    "/stores/geocode",
    dependencies=[Depends(require_capability("stores.manage"))],
)
async def geocode_store(
    request: Request, query: Annotated[str, Query(min_length=1)]
) -> list[dict[str, str | float]]:
    return await request.app.state.open_meteo_provider.geocode(query)


@router.get(
    "/stores/timezone",
    dependencies=[Depends(require_capability("stores.manage"))],
)
async def timezone_for_store_location(
    request: Request,
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
) -> dict[str, str]:
    timezone = await request.app.state.open_meteo_provider.timezone(
        latitude, longitude
    )
    if timezone is None:
        raise HTTPException(503, "暂时无法识别该位置的时区，请稍后重试")
    return {"timezone": timezone}


@router.get("/stores", dependencies=[Depends(require_capability("stores.manage"))])
async def list_stores(session: Session) -> list[dict[str, Any]]:
    stores = (await session.scalars(select(Store).order_by(Store.name, Store.id))).all()
    return [_store_payload(store) for store in stores]


@router.post("/stores", status_code=201)
async def create_store(
    body: StoreCreate, session: Session, actor: StoresManager
) -> dict[str, Any]:
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
    store_id: int, body: StorePatch, session: Session, actor: StoresManager
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


STORE_PROTECTED_REFERENCES = (
    StoreDailyRecord.store_id,
    IncomeCategory.store_id,
    IncomeConfigVersion.store_id,
    DailyBriefing.store_id,
    ScheduledTaskLog.store_id,
    SystemAlert.store_id,
)


async def _store_has_protected_references(session: Session, store_id: int) -> bool:
    for store_id_column in STORE_PROTECTED_REFERENCES:
        if await session.scalar(select(exists().where(store_id_column == store_id))):
            return True
    return False


def _is_initial_store_create_audit(audit: AuditLog, store_id: int) -> bool:
    after = audit.after_json
    return (
        audit.operation_domain == "admin"
        and audit.operation_type == "create"
        and audit.record_id == store_id
        and audit.before_json is None
        and isinstance(after, dict)
        and after.get("id") == store_id
        and after.get("standard_work_hours") == 8
    )


async def _initial_store_create_audit_for_delete(
    session: Session, store_id: int
) -> AuditLog | None:
    audits = list(
        await session.scalars(
            select(AuditLog)
            .where(AuditLog.store_id == store_id)
            .order_by(AuditLog.id)
            .with_for_update()
        )
    )
    if not audits:
        return None
    if len(audits) == 1 and _is_initial_store_create_audit(audits[0], store_id):
        return audits[0]
    raise HTTPException(409, "该门店已有业务或历史记录，请停用门店而不是删除")


@router.delete("/stores/{store_id}", status_code=204)
async def delete_store(store_id: int, session: Session, actor: StoresManager) -> None:
    store = await session.scalar(
        select(Store).where(Store.id == store_id).with_for_update()
    )
    if store is None:
        raise HTTPException(404, "Store not found")
    if await _store_has_protected_references(session, store_id):
        raise HTTPException(409, "该门店已有业务或历史记录，请停用门店而不是删除")
    initial_create_audit = await _initial_store_create_audit_for_delete(session, store_id)

    before = _store_payload(store)
    try:
        if initial_create_audit is not None:
            initial_create_audit.store_id = None
        await session.execute(delete(StoreMember).where(StoreMember.store_id == store_id))
        await session.execute(delete(StoreSetting).where(StoreSetting.store_id == store_id))
        await session.delete(store)
        # Force foreign-key checks while the transaction and row lock are still held.
        await session.flush()
        add_admin_audit(
            session,
            actor_id=actor.id,
            store_id=None,
            record_id=store_id,
            operation_type="delete",
            description=f"Deleted unused store {store.name}",
            before=before,
            after=None,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            409, "该门店已有业务或历史记录，请停用门店而不是删除"
        ) from exc


@router.get(
    "/stores/{store_id}/members",
    dependencies=[Depends(require_capability("stores.manage"))],
)
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
    store_id: int, body: MemberReplace, session: Session, actor: StoresManager
) -> dict[str, Any]:
    store = await _require_store(session, store_id)
    if not store.is_active:
        raise HTTPException(409, "停用门店不能分配用户")
    user_ids = sorted(set(body.user_ids))
    users = await _require_users(session, user_ids)
    if any(user.role == "admin" for user in users):
        raise HTTPException(409, "管理员默认可访问全部门店，无需分配门店")
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


@router.get(
    "/income-categories",
    dependencies=[Depends(require_capability("income_config.manage"))],
)
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
    body: CategoryCreate, session: Session, actor: IncomeConfigManager
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
    await IncomeConfigService(session).publish_categories(category.store_id, actor)
    response_payload = _category_payload(category)
    await session.commit()
    return response_payload


@router.patch("/income-categories/{category_id}")
async def patch_income_category(
    category_id: int,
    body: CategoryPatch,
    request: Request,
    session: Session,
    actor: IncomeConfigManager,
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
        before_records = {record.id: record_snapshot(record) for record in records}

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
        await session.flush()
        for record in records:
            await session.refresh(record, attribute_names=["updated_at", "items"])
            _add_ledger_recalculation_audit(
                session,
                actor_id=actor.id,
                record=record,
                before=before_records[record.id],
                after=record_snapshot(record),
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
    await IncomeConfigService(session).publish_categories(category.store_id, actor)
    response_payload = _category_payload(category)
    await session.commit()
    if records:
        store = await session.get(Store, category.store_id)
        if store is not None:
            local_date = datetime.now(ZoneInfo(store.timezone)).date()
            record_dates = {record.date for record in records}
            card_types = []
            if local_date - timedelta(days=1) in record_dates:
                card_types.append("yesterday")
            if local_date in record_dates:
                card_types.append("today")
            if card_types:
                try:
                    await BriefingService(
                        session, request.app.state.weather_service
                    ).regenerate(store.id, card_types, local_date=local_date)
                    await session.commit()
                except Exception:
                    await session.rollback()
    return response_payload


@router.delete("/income-categories/{category_id}", status_code=204)
async def delete_unused_category(
    category_id: int, session: Session, actor: IncomeConfigManager
) -> None:
    await IncomeConfigService(session).delete_unused(category_id, actor)
    await session.commit()


@router.get("/alerts", dependencies=[Depends(require_capability("audit.view"))])
async def list_alerts(session: Session) -> list[dict[str, Any]]:
    alerts = (
        await session.scalars(
            select(SystemAlert).order_by(SystemAlert.created_at.desc(), SystemAlert.id.desc())
        )
    ).all()
    return [_alert_payload(alert) for alert in alerts]


@router.get("/task-logs", dependencies=[Depends(require_capability("audit.view"))])
async def list_task_logs(session: Session) -> list[dict[str, Any]]:
    task_logs = (
        await session.scalars(
            select(ScheduledTaskLog).order_by(
                ScheduledTaskLog.created_at.desc(), ScheduledTaskLog.id.desc()
            )
        )
    ).all()
    return [_task_log_payload(task_log) for task_log in task_logs]
