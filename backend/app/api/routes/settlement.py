from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, Session
from app.models.identity import Store, User
from app.schemas.settlement import (
    CompanyCreate,
    CompanyPatch,
    CompanyResponse,
    RecordCreate,
    RecordPatch,
    RevisionBody,
    SettlementMonthResponse,
    SettlementRecordResponse,
)
from app.services.access import require_company_settlement_access
from app.services.settlement import SettlementCompanyService, SettlementRecordService


router = APIRouter(prefix="/settlements", tags=["company-settlement"])


async def require_enabled_settlement_store(
    store_id: int,
    user: CurrentUser,
    session: Session,
) -> tuple[User, Store]:
    return await require_company_settlement_access(session, user_id=user.id, store_id=store_id)


EnabledSettlementStore = Annotated[tuple[User, Store], Depends(require_enabled_settlement_store)]


@router.get("/{store_id}")
async def settlement_workspace(
    store_id: int,
    access: EnabledSettlementStore,
) -> dict[str, int | str | bool]:
    """Return the gated shell used by later settlement vertical slices."""
    _, store = access
    return {
        "store_id": store.id,
        "store_name": store.name,
        "company_settlement_enabled": True,
    }


def company_service(session: Session, access: EnabledSettlementStore) -> SettlementCompanyService:
    user, store = access
    return SettlementCompanyService(session, store_id=store.id, actor_id=user.id)


def record_service(session: Session, access: EnabledSettlementStore) -> SettlementRecordService:
    user, store = access
    return SettlementRecordService(session, store=store, actor_id=user.id)


@router.get("/{store_id}/months/{opening_month}", response_model=SettlementMonthResponse)
async def settlement_month(
    store_id: int,
    opening_month: str,
    access: EnabledSettlementStore,
    session: Session,
) -> SettlementMonthResponse:
    return await record_service(session, access).month(opening_month)


@router.post(
    "/{store_id}/records",
    response_model=SettlementRecordResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_settlement_record(
    store_id: int,
    body: RecordCreate,
    access: EnabledSettlementStore,
    session: Session,
) -> SettlementRecordResponse:
    return await record_service(session, access).create(
        company_id=body.company_id,
        opening_month=body.opening_month,
        amount=body.amount,
    )


@router.patch("/{store_id}/records/{record_id}", response_model=SettlementRecordResponse)
async def update_settlement_record(
    store_id: int,
    record_id: int,
    body: RecordPatch,
    access: EnabledSettlementStore,
    session: Session,
) -> SettlementRecordResponse:
    return await record_service(session, access).update(
        record_id,
        company_id=body.company_id,
        amount=body.amount,
        revision=body.revision,
    )


@router.delete("/{store_id}/records/{record_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_settlement_record(
    store_id: int,
    record_id: int,
    body: RevisionBody,
    access: EnabledSettlementStore,
    session: Session,
) -> Response:
    await record_service(session, access).delete(record_id, revision=body.revision)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{store_id}/companies", response_model=list[CompanyResponse])
async def list_companies(
    store_id: int,
    access: EnabledSettlementStore,
    session: Session,
    archived: bool = Query(False),
) -> list[CompanyResponse]:
    return await company_service(session, access).list(active=not archived)


@router.post(
    "/{store_id}/companies",
    response_model=CompanyResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_company(
    store_id: int,
    body: CompanyCreate,
    access: EnabledSettlementStore,
    session: Session,
) -> CompanyResponse:
    return await company_service(session, access).create(body.name)


@router.patch("/{store_id}/companies/{company_id}", response_model=CompanyResponse)
async def rename_company(
    store_id: int,
    company_id: int,
    body: CompanyPatch,
    access: EnabledSettlementStore,
    session: Session,
) -> CompanyResponse:
    service = company_service(session, access)
    return await service.rename(company_id, body.name)


@router.post("/{store_id}/companies/{company_id}/archive", response_model=CompanyResponse)
async def archive_company(
    store_id: int,
    company_id: int,
    access: EnabledSettlementStore,
    session: Session,
) -> CompanyResponse:
    service = company_service(session, access)
    return await service.set_active(company_id, active=False)


@router.post("/{store_id}/companies/{company_id}/restore", response_model=CompanyResponse)
async def restore_company(
    store_id: int,
    company_id: int,
    access: EnabledSettlementStore,
    session: Session,
) -> CompanyResponse:
    service = company_service(session, access)
    return await service.set_active(company_id, active=True)


@router.delete("/{store_id}/companies/{company_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_company(
    store_id: int,
    company_id: int,
    access: EnabledSettlementStore,
    session: Session,
) -> Response:
    service = company_service(session, access)
    await service.delete(company_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
