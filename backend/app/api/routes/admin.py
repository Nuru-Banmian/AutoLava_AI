from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Annotated, Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError

from app.api.deps import Session, require_admin, require_capability
from app.core.database import sqlite_short_write
from app.core.security import hash_password
from app.models.identity import Store, StoreMember, User
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
from app.services.briefing import BriefingService
from app.services.access import require_fresh_store_access, require_fresh_user
from app.services.income_config import IncomeConfigService
from app.services.owner import is_owner, owner_username
from app.services.weather import FrozenWeatherLocation

router = APIRouter(prefix="/admin", tags=["admin"])
UsersManager = Annotated[User, Depends(require_capability("users.manage"))]
StoresManager = Annotated[User, Depends(require_capability("stores.manage"))]
IncomeConfigManager = Annotated[
    User, Depends(require_capability("income_config.manage"))
]


def _require_can_assign_role(actor: User, role: str | None) -> None:
    if role == "admin" and not is_owner(actor):
        raise HTTPException(403, "只有最终管理员可以授予管理员角色")


def _require_can_manage_target(actor: User, target: User) -> None:
    if is_owner(target):
        raise HTTPException(403, "最终管理员账号受保护")
    if target.role == "admin" and not is_owner(actor):
        raise HTTPException(403, "只有最终管理员可以管理管理员账号")


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
    }


def _managed_user_payload(user: User, store_ids: list[int]) -> dict[str, Any]:
    return _user_payload(user) | {"store_ids": store_ids}


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
        raise HTTPException(409, "归档门店不能分配给用户")


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
    statement = select(User).order_by(User.username, User.id)
    configured_owner = owner_username()
    if configured_owner:
        statement = statement.where(User.username != configured_owner)
    users = (await session.scalars(statement)).all()
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
    actor_id = actor.id
    next_store_ids = [] if body.role == "admin" else sorted(set(body.store_ids))
    next_password_hash = hash_password(body.password)
    try:
        async with sqlite_short_write(session):
            fresh_actor = await require_fresh_user(
                session, user_id=actor_id, capability="users.manage"
            )
            _require_can_assign_role(fresh_actor, body.role)
            await _require_stores(session, next_store_ids)
            user = User(
                username=body.username,
                password_hash=next_password_hash,
                role=body.role,
            )
            session.add(user)
            await session.flush()
            session.add_all(
                StoreMember(store_id=store_id, user_id=user.id)
                for store_id in next_store_ids
            )
            response = _managed_user_payload(user, next_store_ids)
    except IntegrityError as exc:
        raise HTTPException(409, "Username already exists") from exc
    return response


@router.patch("/users/{user_id}")
async def patch_user(
    user_id: int, body: UserPatch, session: Session, actor: UsersManager
) -> dict[str, Any]:
    next_password_hash = (
        hash_password(body.password) if body.password is not None else None
    )
    actor_id = actor.id
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(
            session, user_id=actor_id, capability="users.manage"
        )
        active_admins: list[User] = []
        removes_active_admin = body.is_active is False or body.role == "user"
        if removes_active_admin:
            active_admins = list(
                await session.scalars(
                    select(User)
                    .where(User.role == "admin", User.is_active.is_(True))
                    .order_by(User.id)
                    .execution_options(populate_existing=True)
                )
            )
        user = await session.get(User, user_id, populate_existing=True)
        if user is None:
            raise HTTPException(404, "User not found")
        _require_can_manage_target(fresh_actor, user)
        _require_can_assign_role(fresh_actor, body.role)
        if body.is_active is False and user.is_active:
            if user.id == actor_id:
                raise HTTPException(
                    409, "You cannot deactivate your current account"
                )
            if user.role == "admin" and len(active_admins) <= 1:
                raise HTTPException(
                    409, "At least one active administrator is required"
                )
        if body.role == "user" and user.role == "admin" and user.is_active:
            if len(active_admins) <= 1:
                raise HTTPException(
                    409, "At least one active administrator is required"
                )
        previous_store_ids = await _user_store_ids(session, user.id)
        includes_access_change = (
            body.role is not None or body.store_ids is not None
        )
        if next_password_hash is not None:
            user.password_hash = next_password_hash
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
            await session.execute(
                delete(StoreMember).where(StoreMember.user_id == user.id)
            )
            session.add_all(
                StoreMember(store_id=store_id, user_id=user.id)
                for store_id in next_store_ids
            )
        response = _managed_user_payload(user, next_store_ids)
    return response


@router.delete("/users/{user_id}", status_code=204)
async def delete_unused_user(
    user_id: int, session: Session, actor: UsersManager
) -> None:
    actor_id = actor.id
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(
            session, user_id=actor_id, capability="users.manage"
        )
        user = await session.get(User, user_id, populate_existing=True)
        if user is None:
            raise HTTPException(404, "User not found")
        _require_can_manage_target(fresh_actor, user)
        if user.id == actor_id:
            raise HTTPException(409, "You cannot delete your current account")
        ledger_references = await session.scalar(
            select(func.count())
            .select_from(StoreDailyRecord)
            .where(
                (StoreDailyRecord.created_by == user.id)
                | (StoreDailyRecord.updated_by == user.id)
            )
        )
        if ledger_references:
            raise HTTPException(
                409, "该用户已有历史记录，不能永久删除；请停用账号"
            )
        await session.execute(
            delete(StoreMember).where(StoreMember.user_id == user.id)
        )
        await session.delete(user)


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
    actor_id = actor.id
    async with sqlite_short_write(session):
        await require_fresh_user(
            session, user_id=actor_id, capability="stores.manage"
        )
        store = Store(**body.model_dump())
        session.add(store)
        await session.flush()
        response = _store_payload(store)
    return response


@router.patch("/stores/{store_id}")
async def patch_store(
    store_id: int, body: StorePatch, session: Session, actor: StoresManager
) -> dict[str, Any]:
    actor_id = actor.id
    async with sqlite_short_write(session):
        await require_fresh_user(
            session, user_id=actor_id, capability="stores.manage"
        )
        store = await session.get(Store, store_id, populate_existing=True)
        if store is None or not store.is_active:
            raise HTTPException(404, "Store not found")
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(store, field, value)
        response = _store_payload(store)
    return response


STORE_PROTECTED_REFERENCES = (
    StoreDailyRecord.store_id,
    DailyBriefing.store_id,
    ScheduledTaskLog.store_id,
    SystemAlert.store_id,
)


async def _store_has_protected_references(session: Session, store_id: int) -> bool:
    for store_id_column in STORE_PROTECTED_REFERENCES:
        if await session.scalar(select(exists().where(store_id_column == store_id))):
            return True
    return False


@router.delete("/stores/{store_id}", status_code=204)
async def delete_store(store_id: int, session: Session, actor: StoresManager) -> None:
    actor_id = actor.id
    try:
        async with sqlite_short_write(session):
            await require_fresh_user(
                session, user_id=actor_id, capability="stores.manage"
            )
            store = await session.get(Store, store_id, populate_existing=True)
            if store is None or not store.is_active:
                raise HTTPException(404, "Store not found")
            if await _store_has_protected_references(session, store_id):
                raise HTTPException(
                    409, "该门店已有业务或历史记录，请归档门店而不是删除"
                )
            await session.execute(
                delete(StoreMember).where(StoreMember.store_id == store_id)
            )
            await session.execute(
                delete(IncomeCategory).where(
                    IncomeCategory.store_id == store_id
                )
            )
            await session.delete(store)
            # Force foreign-key checks before the transaction is committed.
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(
            409, "该门店已有业务或历史记录，请归档门店而不是删除"
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
    actor_id = actor.id
    user_ids = sorted(set(body.user_ids))
    async with sqlite_short_write(session):
        await require_fresh_store_access(
            session,
            user_id=actor_id,
            store_id=store_id,
            capability="stores.manage",
        )
        users = await _require_users(session, user_ids)
        if any(user.role == "admin" for user in users):
            raise HTTPException(
                409, "管理员默认可访问全部门店，无需分配门店"
            )
        await session.execute(
            delete(StoreMember).where(StoreMember.store_id == store_id)
        )
        session.add_all(
            StoreMember(store_id=store_id, user_id=user_id)
            for user_id in user_ids
        )
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


async def _require_fresh_category_manager(
    session: Session, *, actor_id: int, category_id: int
) -> tuple[IncomeCategory, Store]:
    category = await session.get(
        IncomeCategory, category_id, populate_existing=True
    )
    if category is None:
        raise HTTPException(404, "Category not found")
    _, store = await require_fresh_store_access(
        session,
        user_id=actor_id,
        store_id=category.store_id,
        capability="income_config.manage",
    )
    return category, store


@router.post("/income-categories", status_code=201)
async def create_income_category(
    body: CategoryCreate, session: Session, actor: IncomeConfigManager
) -> dict[str, Any]:
    actor_id = actor.id
    async with sqlite_short_write(session):
        await require_fresh_store_access(
            session,
            user_id=actor_id,
            store_id=body.store_id,
            capability="income_config.manage",
        )
        category = IncomeCategory(**body.model_dump())
        session.add(category)
        await session.flush()
        response_payload = _category_payload(category)
    return response_payload


@router.patch("/income-categories/{category_id}")
async def patch_income_category(
    category_id: int,
    body: CategoryPatch,
    request: Request,
    session: Session,
    actor: IncomeConfigManager,
) -> dict[str, Any]:
    actor_id = actor.id
    async with sqlite_short_write(session):
        category, store = await _require_fresh_category_manager(
            session, actor_id=actor_id, category_id=category_id
        )
        record_dates = set()
        include_changed = (
            body.include_in_total is not None
            and body.include_in_total != category.include_in_total
        )
        if include_changed:
            record_dates = set(
                await session.scalars(
                    select(StoreDailyRecord.date)
                    .join(
                        DailyIncomeItem,
                        DailyIncomeItem.record_id == StoreDailyRecord.id,
                    )
                    .where(DailyIncomeItem.category_id == category.id)
                )
            )
        for field, value in body.model_dump(exclude_none=True).items():
            setattr(category, field, value)
        await session.flush()
        response_payload = _category_payload(category)
        location = FrozenWeatherLocation.from_store(store)
    if record_dates:
        local_date = datetime.now(ZoneInfo(location.timezone)).date()
        card_types = []
        if local_date - timedelta(days=1) in record_dates:
            card_types.append("yesterday")
        if local_date in record_dates:
            card_types.append("today")
        if card_types:
            weather_overrides = None
            if "today" in card_types:
                try:
                    result = await request.app.state.weather_service.get_daily(
                        location, local_date
                    )
                except Exception:
                    result = None
                weather_overrides = {
                    local_date: (
                        result.weather
                        if result is not None
                        else "天气暂时不可用"
                    )
                }
            try:
                async with sqlite_short_write(session):
                    await require_fresh_store_access(
                        session,
                        user_id=actor_id,
                        store_id=location.id,
                        capability="income_config.manage",
                    )
                    await BriefingService(
                        session, request.app.state.weather_service
                    ).regenerate(
                        location.id,
                        card_types,
                        local_date=local_date,
                        weather_overrides=weather_overrides,
                    )
            except Exception:
                pass
    return response_payload


@router.delete("/income-categories/{category_id}", status_code=204)
async def delete_unused_category(
    category_id: int, session: Session, actor: IncomeConfigManager
) -> None:
    actor_id = actor.id
    async with sqlite_short_write(session):
        await _require_fresh_category_manager(
            session, actor_id=actor_id, category_id=category_id
        )
        await IncomeConfigService(session).delete_unused(category_id)


@router.get("/alerts", dependencies=[Depends(require_admin)])
async def list_alerts(session: Session) -> list[dict[str, Any]]:
    alerts = (
        await session.scalars(
            select(SystemAlert).order_by(SystemAlert.created_at.desc(), SystemAlert.id.desc())
        )
    ).all()
    return [_alert_payload(alert) for alert in alerts]


@router.get("/task-logs", dependencies=[Depends(require_admin)])
async def list_task_logs(session: Session) -> list[dict[str, Any]]:
    task_logs = (
        await session.scalars(
            select(ScheduledTaskLog).order_by(
                ScheduledTaskLog.created_at.desc(), ScheduledTaskLog.id.desc()
            )
        )
    ).all()
    return [_task_log_payload(task_log) for task_log in task_logs]
