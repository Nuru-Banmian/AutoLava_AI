from collections.abc import Iterable
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, exists, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import sqlite_short_write
from app.core.password_work import hash_password_async
from app.models.identity import Store, StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import DailyBriefing, ScheduledTaskLog, SystemAlert
from app.models.settlement import SettlementAuditEvent
from app.schemas.admin import (
    CategoryCreate,
    CategoryPatch,
    MemberReplace,
    StoreCreate,
    StorePatch,
    UserCreate,
    UserPatch,
)
from app.schemas.income_config import IncomeCategoryVersionBody
from app.services.access import (
    require_fresh_store_access,
    require_fresh_user,
    require_store_scope,
    store_scope_clause,
)
from app.services.briefing import BriefingService
from app.services.income_config import IncomeConfigService, require_category_manager
from app.services.owner import is_owner, is_administrator, owner_username
from app.services.sessions import revoke_all
from app.services.weather import FrozenWeatherLocation
from app.services.employee_access import (
    employee_management_clause,
    managed_user_payload,
    replace_editors,
    require_manage_target,
)


def _require_can_assign_role(actor: User, role: str | None) -> None:
    if role == "admin" and not is_owner(actor):
        raise HTTPException(403, "只有最终管理员可以授予管理员角色")


def _decimal(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _user_payload(user: User) -> dict[str, Any]:
    return {
        "id": user.id,
        "username": user.username,
        "role": user.role,
        "is_active": user.is_active,
    }


def _store_payload(store: Store) -> dict[str, Any]:
    return {
        "id": store.id,
        "name": store.name,
        "description": store.description,
        "description_revision": store.description_revision,
        "address": store.address,
        "latitude": _decimal(store.latitude),
        "longitude": _decimal(store.longitude),
        "timezone": store.timezone,
        "is_active": store.is_active,
        "company_settlement_enabled": store.company_settlement_enabled,
        "wash_count_enabled": store.wash_count_enabled,
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


async def _require_store(session: AsyncSession, store_id: int) -> Store:
    store = await session.get(Store, store_id)
    if store is None:
        raise HTTPException(404, "Store not found")
    return store


async def _require_users(session: AsyncSession, user_ids: Iterable[int]) -> list[User]:
    unique_ids = sorted(set(user_ids))
    if not unique_ids:
        return []
    users = list(
        await session.scalars(select(User).where(User.id.in_(unique_ids)).order_by(User.id))
    )
    if {user.id for user in users} != set(unique_ids):
        raise HTTPException(404, "User not found")
    return users


async def _require_stores(
    session: AsyncSession, store_ids: Iterable[int], *, allow_archived: bool = False
) -> None:
    unique_ids = sorted(set(store_ids))
    if not unique_ids:
        return
    stores = list(await session.scalars(select(Store).where(Store.id.in_(unique_ids))))
    if {store.id for store in stores} != set(unique_ids):
        raise HTTPException(404, "Store not found")
    if not allow_archived and any(not store.is_active for store in stores):
        raise HTTPException(409, "归档门店不能分配给用户")


async def _user_store_ids(session: AsyncSession, user_id: int) -> list[int]:
    return list(
        await session.scalars(
            select(StoreMember.store_id)
            .where(StoreMember.user_id == user_id)
            .order_by(StoreMember.store_id)
        )
    )


async def _employee_manager(
    session: AsyncSession, actor: User, role: str, manager_id: int | None
) -> User | None:
    if role == "admin":
        if manager_id is not None:
            raise HTTPException(422, "管理员不能设置员工归属")
        return None
    manager = (
        await session.get(User, manager_id, populate_existing=True)
        if manager_id is not None
        else await session.scalar(select(User).where(User.username == owner_username()))
    )
    if manager is None or not is_administrator(manager):
        raise HTTPException(422, "员工必须归属主管理员或从管理员")
    return manager


async def _validate_assignment(
    session: AsyncSession,
    store_ids: list[int],
    manager: User | None,
    role: str,
    *,
    retained_ids: Iterable[int] = (),
) -> None:
    await _require_stores(session, store_ids, allow_archived=True)
    if role != "admin":
        await _require_stores(session, set(store_ids) - set(retained_ids))
    if manager is not None:
        for store_id in store_ids:
            try:
                await require_store_scope(session, manager, store_id)
            except HTTPException as exc:
                raise HTTPException(403, "员工门店范围不能超出所属管理员范围") from exc


async def _replace_user_scope(session: AsyncSession, user: User, next_ids: list[int]) -> None:
    previous_ids = await _user_store_ids(session, user.id)
    removed = set(previous_ids) - set(next_ids)
    if removed:
        await revoke_all(session, user.auth_identity)
        if is_administrator(user):
            employees = (
                await session.scalars(select(User).where(User.manager_id == user.id))
            ).all()
            for employee in employees:
                employee_ids = await _user_store_ids(session, employee.id)
                if removed & set(employee_ids):
                    await session.execute(
                        delete(StoreMember).where(
                            StoreMember.user_id == employee.id, StoreMember.store_id.in_(removed)
                        )
                    )
                    await revoke_all(session, employee.auth_identity)
    await session.execute(delete(StoreMember).where(StoreMember.user_id == user.id))
    session.add_all(StoreMember(store_id=store_id, user_id=user.id) for store_id in next_ids)


async def _require_no_employees(session: AsyncSession, user_id: int) -> None:
    if await session.scalar(select(exists().where(User.manager_id == user_id))):
        raise HTTPException(409, "请先转移该管理员的员工归属")


STORE_PROTECTED_REFERENCES = (
    StoreDailyRecord.store_id,
    DailyBriefing.store_id,
    ScheduledTaskLog.store_id,
    SystemAlert.store_id,
)


async def _store_has_protected_references(session: AsyncSession, store_id: int) -> bool:
    for store_id_column in STORE_PROTECTED_REFERENCES:
        if await session.scalar(select(exists().where(store_id_column == store_id))):
            return True
    return False


async def create_user(body: UserCreate, session: AsyncSession, actor: User) -> dict[str, Any]:
    actor_id = actor.id
    next_store_ids = sorted(set(body.store_ids))
    await session.commit()
    next_password_hash = await hash_password_async(body.password)
    try:
        async with sqlite_short_write(session):
            fresh_actor = await require_fresh_user(
                session, user_id=actor_id, capability="users.manage"
            )
            _require_can_assign_role(fresh_actor, body.role)
            if body.role == "user" and is_owner(fresh_actor) and body.manager_id is None:
                raise HTTPException(422, "必须选择员工所属管理员")
            if not is_owner(fresh_actor) and body.manager_id not in (None, fresh_actor.id):
                raise HTTPException(403, "不能指定其他员工归属")
            manager = await _employee_manager(
                session,
                fresh_actor,
                body.role,
                fresh_actor.id
                if body.role == "user" and not is_owner(fresh_actor)
                else body.manager_id,
            )
            await _validate_assignment(session, next_store_ids, manager, body.role)
            user = User(
                username=body.username,
                password_hash=next_password_hash,
                role=body.role,
                manager_id=manager.id if manager else None,
                creator_id=fresh_actor.id if body.role == "user" else None,
            )
            session.add(user)
            await session.flush()
            session.add_all(
                StoreMember(store_id=store_id, user_id=user.id) for store_id in next_store_ids
            )
            await replace_editors(session, fresh_actor, user, body.editor_ids)
            response = await managed_user_payload(session, fresh_actor, user, next_store_ids)
    except IntegrityError as exc:
        raise HTTPException(409, "Username already exists") from exc
    return response


async def patch_user(
    user_id: int, body: UserPatch, session: AsyncSession, actor: User
) -> dict[str, Any]:
    if body.password is not None:
        await session.commit()
        next_password_hash = await hash_password_async(body.password)
    else:
        next_password_hash = None
    actor_id = actor.id
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(session, user_id=actor_id, capability="users.manage")
        active_admins: list[User] = []
        removes_active_admin = body.is_active is False or body.role == "user"
        if removes_active_admin:
            active_admins = list(
                await session.scalars(
                    select(User)
                    .where(
                        (User.role == "admin") | (User.username == owner_username()),
                        User.is_active.is_(True),
                    )
                    .order_by(User.id)
                    .execution_options(populate_existing=True)
                )
            )
        user = await session.get(User, user_id, populate_existing=True)
        if user is None:
            raise HTTPException(404, "User not found")
        await require_manage_target(session, fresh_actor, user)
        _require_can_assign_role(fresh_actor, body.role)
        if body.is_active is False and user.is_active:
            if user.id == actor_id:
                raise HTTPException(409, "You cannot deactivate your current account")
            if user.role == "admin" and len(active_admins) <= 1:
                raise HTTPException(409, "At least one active administrator is required")
        if body.role == "user" and user.role == "admin" and user.is_active:
            if len(active_admins) <= 1:
                raise HTTPException(409, "At least one active administrator is required")
        previous_store_ids = await _user_store_ids(session, user.id)
        demotes_administrator = user.role == "admin" and body.role == "user"
        if demotes_administrator:
            await _require_no_employees(session, user.id)
        next_role = body.role or user.role
        manager_changed = "manager_id" in body.model_fields_set
        if manager_changed and not is_owner(fresh_actor):
            raise HTTPException(403, "只有主管理员可以转移员工归属")
        if manager_changed and next_role == "user" and body.manager_id is None:
            raise HTTPException(422, "必须选择员工所属管理员")
        manager_id = body.manager_id if manager_changed else user.manager_id
        if next_role == "admin":
            manager_id = None
        manager = await _employee_manager(session, fresh_actor, next_role, manager_id)
        if manager is not None and manager.id == user.id:
            raise HTTPException(422, "员工不能归属自己")
        next_store_ids = (
            sorted(set(body.store_ids)) if body.store_ids is not None else previous_store_ids
        )
        if body.store_ids is not None and not is_owner(fresh_actor):
            for store_id in next_store_ids:
                await _validate_assignment(
                    session, [store_id], fresh_actor, next_role, retained_ids=previous_store_ids
                )
            visible_ids = set(
                await session.scalars(
                    select(Store.id).where(await store_scope_clause(session, fresh_actor))
                )
            )
            next_store_ids = sorted(set(next_store_ids) | (set(previous_store_ids) - visible_ids))
        if manager_changed and body.store_ids is None and manager is not None:
            next_store_ids = [
                store_id
                for store_id in next_store_ids
                if await session.scalar(
                    select(Store.id).where(
                        Store.id == store_id, await store_scope_clause(session, manager)
                    )
                )
                is not None
            ]
        if body.store_ids is not None or manager_changed or body.role is not None:
            await _validate_assignment(
                session, next_store_ids, manager, next_role, retained_ids=previous_store_ids
            )
        if user.manager_id != (manager.id if manager else None):
            await revoke_all(session, user.auth_identity)
        user.manager_id = manager.id if manager else None
        if next_password_hash is not None:
            user.password_hash = next_password_hash
        if body.is_active is not None:
            user.is_active = body.is_active
        if body.role is not None:
            user.role = body.role
        if next_role == "admin":
            user.creator_id = None
            await replace_editors(session, fresh_actor, user, [])
        elif demotes_administrator:
            user.creator_id = fresh_actor.id
        if body.editor_ids is not None:
            await replace_editors(session, fresh_actor, user, body.editor_ids)
        if body.store_ids is not None or manager_changed or body.role is not None:
            await _replace_user_scope(session, user, next_store_ids)
        removes_store_access = bool(set(previous_store_ids) - set(next_store_ids))
        if (
            next_password_hash is not None
            or body.is_active is False
            or demotes_administrator
            or removes_store_access
        ):
            await revoke_all(session, user.auth_identity)
        response = await managed_user_payload(session, fresh_actor, user, next_store_ids)
    return response


async def delete_unused_user(user_id: int, session: AsyncSession, actor: User) -> None:
    actor_id = actor.id
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(session, user_id=actor_id, capability="users.manage")
        user = await session.get(User, user_id, populate_existing=True)
        if user is None:
            raise HTTPException(404, "User not found")
        await require_manage_target(session, fresh_actor, user)
        if user.id == actor_id:
            raise HTTPException(409, "You cannot delete your current account")
        await _require_no_employees(session, user.id)
        ledger_references = await session.scalar(
            select(func.count())
            .select_from(StoreDailyRecord)
            .where(
                (StoreDailyRecord.created_by == user.id) | (StoreDailyRecord.updated_by == user.id)
            )
        )
        if ledger_references:
            raise HTTPException(409, "该用户已有历史记录，不能永久删除；请停用账号")
        await session.execute(delete(StoreMember).where(StoreMember.user_id == user.id))
        await revoke_all(session, user.auth_identity)
        await session.delete(user)


async def create_store(body: StoreCreate, session: AsyncSession, actor: User) -> dict[str, Any]:
    actor_id = actor.id
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(
            session, user_id=actor_id, capability="stores.manage"
        )
        if not is_owner(fresh_actor):
            raise HTTPException(403, "只有主管理员可以创建门店")
        store = Store(**body.model_dump())
        session.add(store)
        await session.flush()
        response = _store_payload(store)
    return response


async def patch_store(
    store_id: int,
    body: StorePatch,
    pending_weather_refresh: Any,
    session: AsyncSession,
    actor: User,
) -> dict[str, Any]:
    actor_id = actor.id
    async with sqlite_short_write(session, begin_immediate=True):
        fresh_actor = await require_fresh_user(
            session, user_id=actor_id, capability="stores.manage"
        )
        store = await session.get(Store, store_id, populate_existing=True)
        if store is None or not store.is_active:
            raise HTTPException(404, "Store not found")
        await require_store_scope(session, fresh_actor, store_id)
        changes = body.model_dump(exclude_none=True, exclude={"expected_description_revision"})
        if "description" in body.model_fields_set:
            if body.expected_description_revision is None:
                raise HTTPException(422, "保存门店描述需要提供描述版本")
            if body.expected_description_revision != store.description_revision:
                raise HTTPException(
                    409,
                    {
                        "code": "store_description_revision_conflict",
                        "message": "门店描述已被修改，请核对最新描述后再保存",
                        "latest": {
                            "description": store.description,
                            "description_revision": store.description_revision,
                        },
                    },
                )
            store.description_revision += 1
        previous_location = FrozenWeatherLocation.from_store(store)
        previous_settlement_enabled = store.company_settlement_enabled
        for field, value in changes.items():
            setattr(store, field, value)
        location_changed = FrozenWeatherLocation.from_store(store) != previous_location
        if (
            "company_settlement_enabled" in changes
            and store.company_settlement_enabled != previous_settlement_enabled
        ):
            session.add(
                SettlementAuditEvent(
                    store_id=store.id,
                    actor_id=fresh_actor.id,
                    action="company_settlement.toggle",
                    entity_type="store",
                    entity_id=store.id,
                    before_state={"company_settlement_enabled": previous_settlement_enabled},
                    after_state={"company_settlement_enabled": store.company_settlement_enabled},
                )
            )
        response = _store_payload(store)
    if location_changed:
        pending_weather_refresh.wake()
    return response


async def delete_store(store_id: int, session: AsyncSession, actor: User) -> None:
    actor_id = actor.id
    try:
        async with sqlite_short_write(session):
            fresh_actor = await require_fresh_user(
                session, user_id=actor_id, capability="stores.manage"
            )
            store = await session.get(Store, store_id, populate_existing=True)
            if store is None or not store.is_active:
                raise HTTPException(404, "Store not found")
            await require_store_scope(session, fresh_actor, store_id)
            if await _store_has_protected_references(session, store_id):
                raise HTTPException(409, "该门店已有业务或历史记录，请归档门店而不是删除")
            await session.execute(delete(StoreMember).where(StoreMember.store_id == store_id))
            await session.execute(delete(IncomeCategory).where(IncomeCategory.store_id == store_id))
            await session.delete(store)
            # Force foreign-key checks before the transaction is committed.
            await session.flush()
    except IntegrityError as exc:
        raise HTTPException(409, "该门店已有业务或历史记录，请归档门店而不是删除") from exc


async def replace_members(
    store_id: int, body: MemberReplace, session: AsyncSession, actor: User
) -> dict[str, Any]:
    actor_id = actor.id
    user_ids = sorted(set(body.user_ids))
    async with sqlite_short_write(session):
        fresh_actor, _ = await require_fresh_store_access(
            session,
            user_id=actor_id,
            store_id=store_id,
            capability="stores.manage",
        )
        users = await _require_users(session, user_ids)
        for user in users:
            await require_manage_target(session, fresh_actor, user)
            if is_administrator(user):
                raise HTTPException(403, "员工成员编辑不能修改管理员授权")
            manager = await _employee_manager(session, fresh_actor, "user", user.manager_id)
            await _validate_assignment(session, [store_id], manager, "user")
        manageable = (
            await session.scalars(
                select(User).where(
                    User.role == "user",
                    User.username != owner_username(),
                    employee_management_clause(fresh_actor),
                )
            )
        ).all()
        for user in manageable:
            ids = await _user_store_ids(session, user.id)
            next_ids = (
                sorted(set(ids) | {store_id})
                if user.id in user_ids
                else [sid for sid in ids if sid != store_id]
            )
            if set(next_ids) != set(ids):
                await _replace_user_scope(session, user, next_ids)
    return {"store_id": store_id, "user_ids": user_ids}


async def create_income_category(
    body: CategoryCreate, session: AsyncSession, actor: User
) -> dict[str, Any]:
    actor_id = actor.id
    async with sqlite_short_write(session):
        _, store = await require_fresh_store_access(
            session,
            user_id=actor_id,
            store_id=body.store_id,
            capability="income_config.manage",
        )
        service = IncomeConfigService(session)
        await service.check_revision(store, body.expected_revision)
        category = IncomeCategory(**body.model_dump(exclude={"expected_revision"}))
        session.add(category)
        await session.flush()
        service.advance(store)
        response_payload = _category_payload(category)
    return response_payload


async def patch_income_category(
    category_id: int,
    body: CategoryPatch,
    weather_service: Any,
    session: AsyncSession,
    actor: User,
) -> dict[str, Any]:
    actor_id = actor.id
    async with sqlite_short_write(session):
        category, store = await require_category_manager(
            session, actor_id=actor_id, category_id=category_id
        )
        service = IncomeConfigService(session)
        await service.check_revision(store, body.expected_revision)
        record_dates = set()
        include_changed = (
            body.include_in_total is not None and body.include_in_total != category.include_in_total
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
        for field, value in body.model_dump(
            exclude_none=True, exclude={"expected_revision"}
        ).items():
            setattr(category, field, value)
        service.advance(store)
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
                    result = await weather_service.get_daily(location, local_date)
                except Exception:
                    result = None
                weather_overrides = {
                    local_date: (result.weather if result is not None else "天气暂时不可用")
                }
            try:
                async with sqlite_short_write(session):
                    await require_fresh_store_access(
                        session,
                        user_id=actor_id,
                        store_id=location.id,
                        capability="income_config.manage",
                    )
                    await BriefingService(session, weather_service).regenerate(
                        location.id,
                        card_types,
                        local_date=local_date,
                        weather_overrides=weather_overrides,
                    )
            except Exception:
                pass
    return response_payload


async def delete_unused_category(
    category_id: int,
    session: AsyncSession,
    actor: User,
    body: IncomeCategoryVersionBody | None = None,
) -> None:
    actor_id = actor.id
    async with sqlite_short_write(session):
        _, store = await require_category_manager(
            session, actor_id=actor_id, category_id=category_id
        )
        service = IncomeConfigService(session)
        await service.check_revision(store, body.expected_revision if body else None)
        await service.delete_unused(category_id)
        service.advance(store)
