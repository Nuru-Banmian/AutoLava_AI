import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import StoreMember
from app.services.settlement import SettlementCompanyService, SettlementRecordService


@pytest.fixture
async def company_service(
    db_session: AsyncSession, user_factory, store_factory
) -> SettlementCompanyService:
    user = await user_factory(username="company-service-user", password="secret")
    store = await store_factory(name="Company service")
    store.company_settlement_enabled = True
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.commit()
    return SettlementCompanyService(db_session, store_id=store.id, actor_id=user.id)


@pytest.fixture
async def record_service(
    db_session: AsyncSession, user_factory, store_factory
) -> tuple[SettlementRecordService, int]:
    user = await user_factory(username="record-service-user", password="secret")
    store = await store_factory(name="Record service")
    store.company_settlement_enabled = True
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.commit()
    company = await SettlementCompanyService(
        db_session, store_id=store.id, actor_id=user.id
    ).create("Fleet")
    service = SettlementRecordService(db_session, store=store, actor_id=user.id)
    record = await service.create(
        company_id=company.id,
        opening_month="2025-12",
        amount=120,
    )
    return service, record.id


async def test_company_service_creates_renames_and_lists_directory_entries(
    company_service: SettlementCompanyService,
) -> None:
    company = await company_service.create("Fleet")
    assert company.normalized_name == "fleet"

    renamed = await company_service.rename(company.id, "Priority Fleet")
    assert renamed.name == "Priority Fleet"
    assert [item.id for item in await company_service.list(active=True)] == [company.id]


async def test_company_service_archives_restores_and_deletes_unused_company(
    company_service: SettlementCompanyService,
) -> None:
    company = await company_service.create("Fleet")

    archived = await company_service.set_active(company.id, active=False)
    assert archived.is_active is False
    assert [item.id for item in await company_service.list(active=False)] == [company.id]

    restored = await company_service.set_active(company.id, active=True)
    assert restored.is_active is True

    await company_service.delete(company.id)
    with pytest.raises(HTTPException) as missing:
        await company_service.get(company.id)
    assert missing.value.status_code == 404


async def test_record_service_summarizes_and_updates_pending_record(
    record_service: tuple[SettlementRecordService, int],
) -> None:
    service, record_id = record_service
    summary = await service.month("2025-12")
    assert summary["pending_amount"] == 120
    assert summary["confirmed_settlement_income"] == 0
    assert summary["monthly_total"] == 0

    updated = await service.update(
        record_id,
        company_id=None,
        amount=150,
        revision=1,
    )
    assert updated.amount == 150
    assert updated.revision == 2


async def test_record_service_confirms_revokes_and_deletes_pending_record(
    record_service: tuple[SettlementRecordService, int],
) -> None:
    service, record_id = record_service
    confirmed = await service.confirm(record_id, revision=1)
    assert confirmed.status == "confirmed"

    pending = await service.revoke_confirmation(
        confirmed.id,
        revision=confirmed.revision,
    )
    assert pending.status == "pending"

    await service.delete(pending.id, revision=pending.revision)
    with pytest.raises(HTTPException) as missing:
        await service.get(pending.id)
    assert missing.value.status_code == 404
