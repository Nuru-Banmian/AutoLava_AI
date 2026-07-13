from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response
from fastapi.responses import JSONResponse

from app.api.deps import Session, StoreAccess, require_store_access
from app.schemas.ledger import LedgerBody
from app.services.audit import record_snapshot
from app.services.ledger import LedgerService

router = APIRouter(prefix="/ledger", tags=["ledger"])


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


@router.put("/{store_id}/{record_date}")
async def put_record(
    store_id: int,
    record_date: date,
    body: LedgerBody,
    session: Session,
    overwrite: bool = False,
    access: StoreAccess = Depends(require_store_access),
) -> Response:
    record, created = await LedgerService(session).upsert(
        store=access.store,
        record_date=record_date,
        payload=body.model_dump(mode="json"),
        actor=access.user,
        overwrite=overwrite,
    )
    return JSONResponse(
        content={
            "id": record.id,
            "date": record.date.isoformat(),
            "daily_revenue": str(record.daily_revenue),
        },
        status_code=201 if created else 200,
    )


@router.delete("/{store_id}/{record_date}", status_code=204)
async def delete_record(
    store_id: int,
    record_date: date,
    session: Session,
    access: StoreAccess = Depends(require_store_access),
) -> Response:
    await LedgerService(session).delete(
        store=access.store,
        record_date=record_date,
        actor=access.user,
    )
    return Response(status_code=204)
