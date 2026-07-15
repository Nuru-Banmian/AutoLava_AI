from datetime import date, datetime, timedelta
from typing import Annotated
from zoneinfo import ZoneInfo

import asyncio

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse

from app.api.deps import Session, StoreAccess, require_store_access
from app.api.routes.dashboard import get_weather_service
from app.schemas.ledger import LedgerBody
from app.services.audit import record_snapshot
from app.services.briefing import BriefingService
from app.services.ledger import LedgerService
from app.services.weather import WeatherService

router = APIRouter(prefix="/ledger", tags=["ledger"])


async def _refresh_briefing_after_commit(
    request: Request,
    session: Session,
    store,
    record_date: date,
    weather_overrides: dict[date, str] | None = None,
) -> None:
    local_date = datetime.now(ZoneInfo(store.timezone)).date()
    card_type = (
        "today"
        if record_date == local_date
        else "yesterday" if record_date == local_date - timedelta(days=1) else None
    )
    if card_type is None:
        return
    await BriefingService(session, get_weather_service(request)).regenerate(
        store.id,
        [card_type],
        local_date=local_date,
        weather_overrides=weather_overrides,
    )
    await session.commit()


async def _safely_refresh_briefing(
    request: Request,
    session: Session,
    store,
    record_date: date,
    weather_overrides: dict[date, str] | None = None,
) -> None:
    try:
        await _refresh_briefing_after_commit(
            request, session, store, record_date, weather_overrides
        )
    except Exception:
        await session.rollback()


@router.get("/{store_id}/recent")
async def recent_records(
    store_id: int,
    session: Session,
    days: Annotated[int, Query(ge=1)] = 7,
    access: StoreAccess = Depends(require_store_access),
) -> list[dict]:
    records = await LedgerService(session).recent(store=access.store, days=days)
    return [record_snapshot(record) for record in records]


@router.get("/{store_id}")
async def get_record_by_query(
    store_id: int,
    session: Session,
    record_date: Annotated[date, Query(alias="date")],
    access: StoreAccess = Depends(require_store_access),
) -> dict:
    record = await LedgerService(session).get(store=access.store, record_date=record_date)
    return record_snapshot(record)


@router.get("/{store_id}/{record_date}")
async def get_record_by_path(
    store_id: int,
    record_date: date,
    session: Session,
    access: StoreAccess = Depends(require_store_access),
) -> dict:
    record = await LedgerService(session).get(store=access.store, record_date=record_date)
    return record_snapshot(record)


@router.get("/{store_id}/{record_date}/form-config")
async def get_form_config(
    store_id: int,
    record_date: date,
    session: Session,
    access: StoreAccess = Depends(require_store_access),
) -> dict:
    return await LedgerService(session).form_config(
        store=access.store, record_date=record_date
    )


@router.put("/{store_id}/{record_date}")
async def put_record(
    store_id: int,
    record_date: date,
    body: LedgerBody,
    request: Request,
    session: Session,
    overwrite: bool = False,
    access: StoreAccess = Depends(require_store_access),
) -> Response:
    payload = body.model_dump(mode="json")
    weather_service: WeatherService = get_weather_service(request)
    try:
        result = await asyncio.wait_for(
            weather_service.get_daily(access.store, record_date), timeout=9
        )
    except Exception:
        result = None
    if result is not None:
        payload.update(
            {
                "weather_auto": result.weather,
                "weather_code": result.weather_code,
                "temperature_max": result.temperature_max,
                "temperature_min": result.temperature_min,
                "precipitation": result.precipitation,
            }
        )
    write = await LedgerService(session).upsert(
        store=access.store,
        record_date=record_date,
        payload=payload,
        actor=access.user,
        overwrite=overwrite,
    )
    record, created = write
    response_content = {
        "id": record.id,
        "date": record.date.isoformat(),
        "daily_revenue": str(record.daily_revenue),
        "row_version": record.row_version,
    }
    await _safely_refresh_briefing(
        request,
        session,
        access.store,
        write.event.record_date,
        {record_date: result.weather if result is not None else "天气暂时不可用"},
    )
    return JSONResponse(
        content=response_content,
        status_code=201 if created else 200,
    )


@router.delete("/{store_id}/{record_date}", status_code=204)
async def delete_record(
    store_id: int,
    record_date: date,
    request: Request,
    session: Session,
    expected_version: Annotated[int, Query(ge=1)],
    access: StoreAccess = Depends(require_store_access),
) -> Response:
    event = await LedgerService(session).delete(
        store=access.store,
        record_date=record_date,
        actor=access.user,
        expected_version=expected_version,
    )
    await _safely_refresh_briefing(request, session, access.store, event.record_date)
    return Response(status_code=204)
