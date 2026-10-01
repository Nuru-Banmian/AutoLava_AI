from app.services import admin_commands
from app.services.admin_commands import (
    _user_payload,
    _managed_user_payload,
    _store_payload,
    _require_store,
    _category_payload,
)
from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy import select

from app.api.deps import Session, require_admin, require_capability
from app.models.identity import Store, StoreMember, User
from app.models.ledger import IncomeCategory
from app.models.operations import ScheduledTaskLog, SystemAlert
from app.schemas.admin import (
    AdminStoreResponse,
    AdminUserResponse,
    CategoryCreate,
    CategoryPatch,
    GeocodeCandidateResponse,
    MemberReplace,
    ScheduledTaskLogResponse,
    StoreCreate,
    StoreMembersResponse,
    StorePatch,
    SystemAlertResponse,
    TimezoneResponse,
    UserCreate,
    UserPatch,
    UserSummaryResponse,
)
from app.schemas.time import timestamp_status, trusted_utc
from app.schemas.income_config import IncomeCategoryResponse, IncomeCategoryVersionBody
from app.services.owner import owner_username

router = APIRouter(prefix="/admin", tags=["admin"])
UsersManager = Annotated[User, Depends(require_capability("users.manage"))]
StoresManager = Annotated[User, Depends(require_capability("stores.manage"))]
IncomeConfigManager = Annotated[User, Depends(require_capability("income_config.manage"))]


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


@router.get("/users", response_model=list[AdminUserResponse], dependencies=[Depends(require_capability("users.manage"))])
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
    return [_managed_user_payload(user, store_ids_by_user.get(user.id, [])) for user in users]


@router.post("/users", status_code=201, response_model=AdminUserResponse)
async def create_user(body: UserCreate, session: Session, actor: UsersManager) -> dict[str, Any]:
    return await admin_commands.create_user(body, session, actor)


@router.patch("/users/{user_id}", response_model=AdminUserResponse)
async def patch_user(
    user_id: int, body: UserPatch, session: Session, actor: UsersManager
) -> dict[str, Any]:
    return await admin_commands.patch_user(user_id, body, session, actor)


@router.delete("/users/{user_id}", status_code=204)
async def delete_unused_user(user_id: int, session: Session, actor: UsersManager) -> None:
    return await admin_commands.delete_unused_user(user_id, session, actor)


@router.get(
    "/users/{user_id}/stores",
    response_model=list[AdminStoreResponse],
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
    response_model=list[GeocodeCandidateResponse],
    dependencies=[Depends(require_capability("stores.manage"))],
)
async def geocode_store(
    request: Request, query: Annotated[str, Query(min_length=1)]
) -> list[dict[str, str | float]]:
    return await request.app.state.open_meteo_provider.geocode(query)


@router.get(
    "/stores/timezone",
    response_model=TimezoneResponse,
    dependencies=[Depends(require_capability("stores.manage"))],
)
async def timezone_for_store_location(
    request: Request,
    latitude: Annotated[float, Query(ge=-90, le=90)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
) -> dict[str, str]:
    timezone = await request.app.state.open_meteo_provider.timezone(latitude, longitude)
    if timezone is None:
        raise HTTPException(503, "暂时无法识别该位置的时区，请稍后重试")
    return {"timezone": timezone}


@router.get("/stores", response_model=list[AdminStoreResponse], dependencies=[Depends(require_capability("stores.manage"))])
async def list_stores(session: Session) -> list[dict[str, Any]]:
    stores = (await session.scalars(select(Store).order_by(Store.name, Store.id))).all()
    return [_store_payload(store) for store in stores]


@router.post("/stores", status_code=201, response_model=AdminStoreResponse)
async def create_store(body: StoreCreate, session: Session, actor: StoresManager) -> dict[str, Any]:
    return await admin_commands.create_store(body, session, actor)


@router.patch("/stores/{store_id}", response_model=AdminStoreResponse)
async def patch_store(
    store_id: int, body: StorePatch, request: Request, session: Session, actor: StoresManager
) -> dict[str, Any]:
    return await admin_commands.patch_store(
        store_id, body, request.app.state.pending_weather_refresh, session, actor
    )


@router.delete("/stores/{store_id}", status_code=204)
async def delete_store(store_id: int, session: Session, actor: StoresManager) -> None:
    return await admin_commands.delete_store(store_id, session, actor)


@router.get(
    "/stores/{store_id}/members",
    response_model=list[UserSummaryResponse],
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


@router.put("/stores/{store_id}/members", response_model=StoreMembersResponse)
async def replace_members(
    store_id: int, body: MemberReplace, session: Session, actor: StoresManager
) -> dict[str, Any]:
    return await admin_commands.replace_members(store_id, body, session, actor)


@router.get(
    "/income-categories",
    response_model=list[IncomeCategoryResponse],
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


@router.post("/income-categories", status_code=201, response_model=IncomeCategoryResponse)
async def create_income_category(
    body: CategoryCreate, session: Session, actor: IncomeConfigManager
) -> dict[str, Any]:
    return await admin_commands.create_income_category(body, session, actor)


@router.patch("/income-categories/{category_id}", response_model=IncomeCategoryResponse)
async def patch_income_category(
    category_id: int,
    body: CategoryPatch,
    request: Request,
    session: Session,
    actor: IncomeConfigManager,
) -> dict[str, Any]:
    return await admin_commands.patch_income_category(
        category_id, body, request.app.state.weather_service, session, actor
    )


@router.delete("/income-categories/{category_id}", status_code=204)
async def delete_unused_category(
    category_id: int,
    session: Session,
    actor: IncomeConfigManager,
    body: IncomeCategoryVersionBody | None = Body(default=None),
) -> None:
    return await admin_commands.delete_unused_category(category_id, session, actor, body)


@router.get("/alerts", response_model=list[SystemAlertResponse], dependencies=[Depends(require_admin)])
async def list_alerts(session: Session) -> list[dict[str, Any]]:
    alerts = (
        await session.scalars(
            select(SystemAlert).order_by(SystemAlert.created_at.desc(), SystemAlert.id.desc())
        )
    ).all()
    return [_alert_payload(alert) for alert in alerts]


@router.get("/task-logs", response_model=list[ScheduledTaskLogResponse], dependencies=[Depends(require_admin)])
async def list_task_logs(session: Session) -> list[dict[str, Any]]:
    task_logs = (
        await session.scalars(
            select(ScheduledTaskLog).order_by(
                ScheduledTaskLog.created_at.desc(), ScheduledTaskLog.id.desc()
            )
        )
    ).all()
    return [_task_log_payload(task_log) for task_log in task_logs]
