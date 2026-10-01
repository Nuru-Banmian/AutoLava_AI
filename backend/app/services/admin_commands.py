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
from app.services.access import require_fresh_store_access, require_fresh_user
from app.services.briefing import BriefingService
from app.services.income_config import IncomeConfigService
from app.services.owner import is_owner
from app.services.sessions import revoke_all
from app.services.weather import FrozenWeatherLocation


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


async def _require_stores(session: AsyncSession, store_ids: Iterable[int]) -> None:
    unique_ids = sorted(set(store_ids))
    if not unique_ids:
        return
    stores = list(await session.scalars(select(Store).where(Store.id.in_(unique_ids))))
    if {store.id for store in stores} != set(unique_ids):
        raise HTTPException(404, "Store not found")
    if any(not store.is_active for store in stores):
        raise HTTPException(409, "归档门店不能分配给用户")


async def _user_store_ids(session: AsyncSession, user_id: int) -> list[int]:
    return list(
        await session.scalars(
            select(StoreMember.store_id)
            .where(StoreMember.user_id == user_id)
            .order_by(StoreMember.store_id)
        )
    )


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


async def _require_fresh_category_manager(
    session: AsyncSession, *, actor_id: int, category_id: int
) -> tuple[IncomeCategory, Store]:
    category = await session.get(IncomeCategory, category_id, populate_existing=True)
    if category is None:
        raise HTTPException(404, "Category not found")
    _, store = await require_fresh_store_access(
        session,
        user_id=actor_id,
        store_id=category.store_id,
        capability="income_config.manage",
    )
    return category, store


async def create_user(body: UserCreate, session: AsyncSession, actor: User) -> dict[str, Any]:
    actor_id = actor.id
    next_store_ids = [] if body.role == "admin" else sorted(set(body.store_ids))
    await session.commit()
    next_password_hash = await hash_password_async(body.password)
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
                StoreMember(store_id=store_id, user_id=user.id) for store_id in next_store_ids
            )
            response = _managed_user_payload(user, next_store_ids)
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
                raise HTTPException(409, "You cannot deactivate your current account")
            if user.role == "admin" and len(active_admins) <= 1:
                raise HTTPException(409, "At least one active administrator is required")
        if body.role == "user" and user.role == "admin" and user.is_active:
            if len(active_admins) <= 1:
                raise HTTPException(409, "At least one active administrator is required")
        previous_store_ids = await _user_store_ids(session, user.id)
        demotes_administrator = user.role == "admin" and body.role == "user"
        includes_access_change = body.role is not None or body.store_ids is not None
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
            await session.execute(delete(StoreMember).where(StoreMember.user_id == user.id))
            session.add_all(
                StoreMember(store_id=store_id, user_id=user.id) for store_id in next_store_ids
            )
        removes_store_access = bool(set(previous_store_ids) - set(next_store_ids))
        if (
            next_password_hash is not None
            or body.is_active is False
            or demotes_administrator
            or removes_store_access
        ):
            await revoke_all(session, user.auth_identity)
        response = _managed_user_payload(user, next_store_ids)
    return response


async def delete_unused_user(user_id: int, session: AsyncSession, actor: User) -> None:
    actor_id = actor.id
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(session, user_id=actor_id, capability="users.manage")
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
        await require_fresh_user(session, user_id=actor_id, capability="stores.manage")
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
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(
            session, user_id=actor_id, capability="stores.manage"
        )
        store = await session.get(Store, store_id, populate_existing=True)
        if store is None or not store.is_active:
            raise HTTPException(404, "Store not found")
        changes = body.model_dump(exclude_none=True)
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
            await require_fresh_user(session, user_id=actor_id, capability="stores.manage")
            store = await session.get(Store, store_id, populate_existing=True)
            if store is None or not store.is_active:
                raise HTTPException(404, "Store not found")
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
        await require_fresh_store_access(
            session,
            user_id=actor_id,
            store_id=store_id,
            capability="stores.manage",
        )
        users = await _require_users(session, user_ids)
        if any(user.role == "admin" for user in users):
            raise HTTPException(409, "管理员默认可访问全部门店，无需分配门店")
        await session.execute(delete(StoreMember).where(StoreMember.store_id == store_id))
        session.add_all(StoreMember(store_id=store_id, user_id=user_id) for user_id in user_ids)
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
        category, store = await _require_fresh_category_manager(
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
        _, store = await _require_fresh_category_manager(
            session, actor_id=actor_id, category_id=category_id
        )
        service = IncomeConfigService(session)
        await service.check_revision(store, body.expected_revision if body else None)
        await service.delete_unused(category_id)
        service.advance(store)
