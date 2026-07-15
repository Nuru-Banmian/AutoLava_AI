from datetime import date
from decimal import Decimal
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import Select, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Session, StoreAccess, require_store_access
from app.models.audit import AuditLog
from app.models.identity import User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.schemas.database import AuditPage, DatabaseFilters, DatabasePage, RollbackResult
from app.services.audit import record_snapshot
from app.services.export import build_ledger_workbook
from app.services.rollback import RollbackService
from app.api.routes.ledger import _safely_refresh_briefing

router = APIRouter(prefix="/database", tags=["database"])


def build_record_query(store_id: int, filters: DatabaseFilters) -> Select:
    conditions = [StoreDailyRecord.store_id == store_id]
    if filters.start is not None:
        conditions.append(StoreDailyRecord.date >= filters.start)
    if filters.end is not None:
        conditions.append(StoreDailyRecord.date <= filters.end)
    if filters.status is not None:
        conditions.append(StoreDailyRecord.is_open == filters.status)
    if filters.weather is not None:
        conditions.append(StoreDailyRecord.weather == filters.weather)
    if filters.activity_query is not None:
        conditions.append(
            func.lower(StoreDailyRecord.activity).contains(
                filters.activity_query.lower(), autoescape=True
            )
        )
    if filters.missing_wash_count:
        conditions.append(StoreDailyRecord.wash_count.is_(None))
    return (
        select(StoreDailyRecord)
        .where(*conditions)
        .order_by(StoreDailyRecord.date.desc(), StoreDailyRecord.id.desc())
    )


def _filters(
    start: date | None,
    end: date | None,
    status: Literal["营业", "休息", "天气停业"] | None,
    weather: str | None,
    activity_query: str | None,
    missing_wash_count: bool,
) -> DatabaseFilters:
    if start is not None and end is not None and start > end:
        raise HTTPException(422, "start must be on or before end")
    return DatabaseFilters(
        start=start,
        end=end,
        status=status,
        weather=weather,
        activity_query=activity_query,
        missing_wash_count=missing_wash_count,
    )


def _category_payload(category: IncomeCategory) -> dict:
    return {
        "id": category.id,
        "name": category.name,
        "include_in_total": category.include_in_total,
        "is_active": category.is_active,
        "sort_order": category.sort_order,
    }


async def _categories_for_query(
    session: AsyncSession,
    *,
    store_id: int,
    record_query: Select,
) -> list[dict]:
    record_ids = record_query.with_only_columns(StoreDailyRecord.id).subquery()
    used_category_ids = select(DailyIncomeItem.category_id).where(
        DailyIncomeItem.record_id.in_(select(record_ids.c.id))
    )
    categories = await session.scalars(
        select(IncomeCategory)
        .where(
            IncomeCategory.store_id == store_id,
            or_(
                IncomeCategory.is_active.is_(True),
                IncomeCategory.id.in_(used_category_ids),
            ),
        )
        .order_by(IncomeCategory.sort_order, IncomeCategory.id)
    )
    return [_category_payload(category) for category in categories]


async def _record_payloads(session: AsyncSession, records: list[StoreDailyRecord]) -> list[dict]:
    user_ids = {value for record in records for value in (record.created_by, record.updated_by)}
    usernames = (
        {}
        if not user_ids
        else dict(
            (await session.execute(select(User.id, User.username).where(User.id.in_(user_ids))))
            .tuples()
            .all()
        )
    )
    return [
        record_snapshot(record)
        | {
            "created_by_name": usernames.get(record.created_by, ""),
            "updated_by_name": usernames.get(record.updated_by, ""),
        }
        for record in records
    ]


async def _query_summary(session: AsyncSession, record_query: Select) -> tuple[int, str]:
    filtered = (
        record_query.order_by(None)
        .with_only_columns(StoreDailyRecord.id, StoreDailyRecord.daily_revenue)
        .subquery()
    )
    total, revenue = (
        await session.execute(
            select(
                func.count(filtered.c.id),
                func.coalesce(func.sum(filtered.c.daily_revenue), Decimal("0.00")),
            )
        )
    ).one()
    return int(total), f"{Decimal(revenue):.2f}"


async def _load_records(session: AsyncSession, record_query: Select) -> list[StoreDailyRecord]:
    records = await session.scalars(record_query.options(selectinload(StoreDailyRecord.items)))
    return list(records)


def _audit_payload(audit: AuditLog, username: str) -> dict:
    return {
        "id": audit.id,
        "record_id": audit.record_id,
        "record_date": None if audit.record_date is None else audit.record_date.isoformat(),
        "operation_type": audit.operation_type,
        "operation_source": audit.operation_source,
        "operator_user_id": audit.operator_user_id,
        "operator_username": username,
        "before": audit.before_json,
        "after": audit.after_json,
        "description": audit.description,
        "requires_approval": audit.requires_approval,
        "approved": audit.approved,
        "rollbackable": audit.rollbackable,
        "created_at": audit.created_at,
    }


@router.post("/{store_id}/history/{audit_id}/rollback", response_model=RollbackResult)
async def rollback_record(
    store_id: int,
    audit_id: int,
    session: Session,
    request: Request,
    access: StoreAccess = Depends(require_store_access),
) -> dict:
    audit = await session.get(AuditLog, audit_id)
    if audit is None or audit.operation_domain != "ledger" or audit.store_id != store_id:
        raise HTTPException(404, "Audit entry not found")
    if not audit.rollbackable:
        raise HTTPException(409, "Audit entry is not rollbackable")
    service = RollbackService(session)
    restored = await service.rollback(audit_id, actor_id=access.user.id)
    if service.last_event is not None:
        await _safely_refresh_briefing(
            request,
            session,
            access.store,
            service.last_event.record_date,
        )
    return {
        "audit_id": audit_id,
        "record": None if restored is None else record_snapshot(restored),
    }


@router.get("/{store_id}/export.xlsx")
async def export_records(
    store_id: int,
    session: Session,
    start: date | None = None,
    end: date | None = None,
    status: Literal["营业", "休息", "天气停业"] | None = None,
    weather: Annotated[str | None, Query(max_length=50)] = None,
    activity_query: Annotated[str | None, Query(max_length=2000)] = None,
    missing_wash_count: bool = False,
    access: StoreAccess = Depends(require_store_access),
) -> Response:
    filters = _filters(start, end, status, weather, activity_query, missing_wash_count)
    record_query = build_record_query(store_id, filters)
    records = await _load_records(session, record_query)
    categories = await _categories_for_query(session, store_id=store_id, record_query=record_query)
    payloads = await _record_payloads(session, records)
    if start is not None and end is not None:
        suffix = f"{start.isoformat()}-{end.isoformat()}"
    elif start is not None:
        suffix = f"from-{start.isoformat()}"
    elif end is not None:
        suffix = f"through-{end.isoformat()}"
    else:
        suffix = "all"
    filename = f"ledger-{access.store.id}-{suffix}.xlsx"
    return Response(
        content=build_ledger_workbook(payloads, categories),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{store_id}/history", response_model=AuditPage)
async def record_history(
    store_id: int,
    session: Session,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    record_id: int | None = None,
    access: StoreAccess = Depends(require_store_access),
) -> dict:
    del access
    conditions = [
        AuditLog.operation_domain == "ledger",
        AuditLog.store_id == store_id,
    ]
    if record_id is not None:
        conditions.append(AuditLog.record_id == record_id)
    total = await session.scalar(
        select(func.count()).select_from(AuditLog).where(*conditions)
    )
    rows = (
        await session.execute(
            select(AuditLog, User.username)
            .join(User, User.id == AuditLog.operator_user_id)
            .where(*conditions)
            .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).all()
    return {
        "items": [_audit_payload(audit, username) for audit, username in rows],
        "total": total or 0,
        "page": page,
        "page_size": page_size,
    }


@router.get("/{store_id}/records", response_model=DatabasePage)
async def record_page(
    store_id: int,
    session: Session,
    start: date | None = None,
    end: date | None = None,
    status: Literal["营业", "休息", "天气停业"] | None = None,
    weather: Annotated[str | None, Query(max_length=50)] = None,
    activity_query: Annotated[str | None, Query(max_length=2000)] = None,
    missing_wash_count: bool = False,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=200)] = 50,
    access: StoreAccess = Depends(require_store_access),
) -> dict:
    del access
    filters = _filters(start, end, status, weather, activity_query, missing_wash_count)
    record_query = build_record_query(store_id, filters)
    total, revenue = await _query_summary(session, record_query)
    page_query = record_query.offset((page - 1) * page_size).limit(page_size)
    records = await _load_records(session, page_query)
    return {
        "items": await _record_payloads(session, records),
        "categories": await _categories_for_query(
            session, store_id=store_id, record_query=page_query
        ),
        "sum_daily_revenue": revenue,
        "total": total,
        "page": page,
        "page_size": page_size,
    }
