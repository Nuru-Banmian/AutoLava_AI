from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.audit import AuditLog
from app.models.identity import Store, User
from app.models.ledger import IncomeCategory, StoreDailyRecord
from app.services.audit import record_snapshot
from app.services.ledger import LedgerService


@dataclass
class LedgerContext:
    user: User
    store: Store
    cash: IncomeCategory
    card: IncomeCategory
    hidden: IncomeCategory


@pytest.fixture
async def ledger_context(db_session, user_factory, store_factory) -> LedgerContext:
    user = await user_factory(username="ledger-user", password="secret")
    store = await store_factory(name="Ledger Store", timezone="Europe/Berlin")
    cash = IncomeCategory(
        store_id=store.id,
        name="Cash",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    card = IncomeCategory(
        store_id=store.id,
        name="Card",
        include_in_total=True,
        is_active=True,
        sort_order=1,
    )
    hidden = IncomeCategory(
        store_id=store.id,
        name="Hidden",
        include_in_total=False,
        is_active=True,
        sort_order=2,
    )
    db_session.add_all([cash, card, hidden])
    await db_session.flush()
    return LedgerContext(user=user, store=store, cash=cash, card=card, hidden=hidden)


@pytest.fixture
def ledger_service(db_session: AsyncSession) -> LedgerService:
    return LedgerService(db_session)


def ledger_payload(context: LedgerContext, *, cash: str = "100.00") -> dict:
    return {
        "is_open": "营业",
        "wash_count": 12,
        "weather": "晴",
        "weather_edited": True,
        "activity": None,
        "items": [{"category_id": context.cash.id, "amount": cash}],
    }


def local_today(context: LedgerContext) -> date:
    return datetime.now(ZoneInfo(context.store.timezone)).date()


async def latest_audit(db_session: AsyncSession, record_id: int) -> AuditLog:
    audit = await db_session.scalar(
        select(AuditLog)
        .where(AuditLog.operation_domain == "ledger", AuditLog.record_id == record_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    assert audit is not None
    return audit


async def test_revenue_uses_only_included_categories(
    ledger_service: LedgerService, ledger_context: LedgerContext
) -> None:
    record, created = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=local_today(ledger_context),
        payload={
            "is_open": "营业",
            "wash_count": 12,
            "weather": "晴",
            "activity": None,
            "daily_revenue": "999999.00",
            "items": [
                {"category_id": ledger_context.cash.id, "amount": "200.00"},
                {"category_id": ledger_context.card.id, "amount": "150.00"},
                {"category_id": ledger_context.hidden.id, "amount": "80.00"},
            ],
        },
        actor=ledger_context.user,
    )

    assert created is True
    assert record.daily_revenue == Decimal("350.00")


async def test_update_writes_complete_before_and_after_snapshots(
    ledger_service: LedgerService,
    ledger_context: LedgerContext,
    db_session: AsyncSession,
) -> None:
    record_date = local_today(ledger_context)
    first, created = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=record_date,
        payload=ledger_payload(ledger_context, cash="100.00"),
        actor=ledger_context.user,
    )
    updated, created_again = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=record_date,
        payload=ledger_payload(ledger_context, cash="120.00"),
        actor=ledger_context.user,
        overwrite=True,
        source="scan",
        requires_approval=True,
        approved=False,
    )

    assert created is True
    assert created_again is False
    assert updated.id == first.id
    audit = await latest_audit(db_session, first.id)
    assert audit.operation_type == "update"
    assert audit.operation_source == "scan"
    assert audit.requires_approval is True
    assert audit.approved is False
    assert audit.before_json["items"][0]["amount"] == "100.00"
    assert audit.after_json["items"][0]["amount"] == "120.00"
    expected_keys = {
        "id",
        "store_id",
        "date",
        "daily_revenue",
        "wash_count",
        "is_open",
        "weather",
        "weather_auto",
        "weather_code",
        "temperature_max",
        "temperature_min",
        "precipitation",
        "activity",
        "weather_edited",
        "scanned",
        "created_by",
        "updated_by",
        "created_at",
        "updated_at",
        "items",
    }
    assert set(audit.before_json) == expected_keys
    assert set(audit.after_json) == expected_keys
    assert set(audit.after_json["items"][0]) == {
        "id",
        "category_id",
        "amount",
        "created_at",
        "updated_at",
    }


async def test_create_audit_matches_canonical_snapshot(
    ledger_service: LedgerService,
    ledger_context: LedgerContext,
    db_session: AsyncSession,
) -> None:
    record, _ = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=local_today(ledger_context),
        payload=ledger_payload(ledger_context),
        actor=ledger_context.user,
    )

    audit = await latest_audit(db_session, record.id)
    assert audit.operation_type == "create"
    assert audit.before_json is None
    assert audit.after_json == record_snapshot(record)


async def test_future_date_is_rejected_without_partial_writes(
    ledger_service: LedgerService,
    ledger_context: LedgerContext,
    db_session: AsyncSession,
) -> None:
    with pytest.raises(HTTPException) as exc_info:
        await ledger_service.upsert(
            store=ledger_context.store,
            record_date=date(2999, 1, 1),
            payload=ledger_payload(ledger_context),
            actor=ledger_context.user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Future ledger dates are not allowed"
    assert await db_session.scalar(select(func.count()).select_from(StoreDailyRecord)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_existing_date_requires_explicit_overwrite(
    ledger_service: LedgerService,
    ledger_context: LedgerContext,
    db_session: AsyncSession,
) -> None:
    record_date = local_today(ledger_context)
    record, _ = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=record_date,
        payload=ledger_payload(ledger_context, cash="100.00"),
        actor=ledger_context.user,
    )

    with pytest.raises(HTTPException) as exc_info:
        await ledger_service.upsert(
            store=ledger_context.store,
            record_date=record_date,
            payload=ledger_payload(ledger_context, cash="200.00"),
            actor=ledger_context.user,
        )

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Record exists; confirm overwrite"
    await db_session.refresh(record, attribute_names=["items"])
    assert record.items[0].amount == Decimal("100.00")
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_rest_day_normalizes_counts_and_all_items_to_zero(
    ledger_service: LedgerService, ledger_context: LedgerContext
) -> None:
    payload = ledger_payload(ledger_context, cash="100.00")
    payload["is_open"] = "休息"
    payload["wash_count"] = 14
    payload["items"].append({"category_id": ledger_context.card.id, "amount": "25.00"})

    record, _ = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=local_today(ledger_context),
        payload=payload,
        actor=ledger_context.user,
    )

    assert record.wash_count == 0
    assert record.daily_revenue == Decimal("0.00")
    assert {item.amount for item in record.items} == {Decimal("0.00")}


async def test_weather_closure_retains_submitted_counts_and_items(
    ledger_service: LedgerService, ledger_context: LedgerContext
) -> None:
    payload = ledger_payload(ledger_context, cash="100.00")
    payload["is_open"] = "天气停业"
    payload["wash_count"] = 3

    record, _ = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=local_today(ledger_context),
        payload=payload,
        actor=ledger_context.user,
    )

    assert record.wash_count == 3
    assert record.daily_revenue == Decimal("100.00")
    assert record.items[0].amount == Decimal("100.00")


async def test_duplicate_category_items_are_rejected_without_writes(
    ledger_service: LedgerService,
    ledger_context: LedgerContext,
    db_session: AsyncSession,
) -> None:
    payload = ledger_payload(ledger_context)
    payload["items"].append({"category_id": ledger_context.cash.id, "amount": "20.00"})

    with pytest.raises(HTTPException) as exc_info:
        await ledger_service.upsert(
            store=ledger_context.store,
            record_date=local_today(ledger_context),
            payload=payload,
            actor=ledger_context.user,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Duplicate income categories are not allowed"
    assert await db_session.scalar(select(func.count()).select_from(StoreDailyRecord)) == 0
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) == 0


async def test_category_must_belong_to_store_and_invalid_overwrite_is_atomic(
    ledger_service: LedgerService,
    ledger_context: LedgerContext,
    db_session: AsyncSession,
    store_factory,
) -> None:
    record_date = local_today(ledger_context)
    record, _ = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=record_date,
        payload=ledger_payload(ledger_context, cash="100.00"),
        actor=ledger_context.user,
    )
    other_store = await store_factory(name="Other Store")
    other_category = IncomeCategory(
        store_id=other_store.id,
        name="Other",
        include_in_total=True,
        is_active=True,
        sort_order=0,
    )
    db_session.add(other_category)
    await db_session.flush()
    invalid = ledger_payload(ledger_context, cash="900.00")
    invalid["items"] = [{"category_id": other_category.id, "amount": "900.00"}]

    with pytest.raises(HTTPException) as exc_info:
        await ledger_service.upsert(
            store=ledger_context.store,
            record_date=record_date,
            payload=invalid,
            actor=ledger_context.user,
            overwrite=True,
        )

    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Income category does not belong to this store"
    await db_session.refresh(record, attribute_names=["items"])
    assert record.daily_revenue == Decimal("100.00")
    assert record.items[0].category_id == ledger_context.cash.id
    assert record.items[0].amount == Decimal("100.00")
    assert await db_session.scalar(select(func.count()).select_from(AuditLog)) == 1


async def test_inactive_category_can_only_be_retained_on_existing_record(
    ledger_service: LedgerService,
    ledger_context: LedgerContext,
    db_session: AsyncSession,
) -> None:
    record_date = local_today(ledger_context)
    record, _ = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=record_date,
        payload=ledger_payload(ledger_context, cash="100.00"),
        actor=ledger_context.user,
    )
    ledger_context.cash.is_active = False
    inactive_new = IncomeCategory(
        store_id=ledger_context.store.id,
        name="Inactive new",
        include_in_total=True,
        is_active=False,
        sort_order=9,
    )
    db_session.add(inactive_new)
    await db_session.flush()

    retained, created = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=record_date,
        payload=ledger_payload(ledger_context, cash="125.00"),
        actor=ledger_context.user,
        overwrite=True,
    )
    assert created is False
    assert retained.items[0].amount == Decimal("125.00")

    invalid = ledger_payload(ledger_context, cash="125.00")
    invalid["items"].append({"category_id": inactive_new.id, "amount": "10.00"})
    with pytest.raises(HTTPException) as exc_info:
        await ledger_service.upsert(
            store=ledger_context.store,
            record_date=record_date,
            payload=invalid,
            actor=ledger_context.user,
            overwrite=True,
        )
    assert exc_info.value.status_code == 422
    assert exc_info.value.detail == "Inactive categories may only be retained on historical records"
    await db_session.refresh(record, attribute_names=["items"])
    assert [item.category_id for item in record.items] == [ledger_context.cash.id]
    assert record.items[0].amount == Decimal("125.00")


async def test_delete_removes_record_and_writes_before_snapshot(
    ledger_service: LedgerService,
    ledger_context: LedgerContext,
    db_session: AsyncSession,
) -> None:
    record_date = local_today(ledger_context)
    record, _ = await ledger_service.upsert(
        store=ledger_context.store,
        record_date=record_date,
        payload=ledger_payload(ledger_context),
        actor=ledger_context.user,
    )
    expected = record_snapshot(record)

    await ledger_service.delete(
        store=ledger_context.store,
        record_date=record_date,
        actor=ledger_context.user,
    )

    assert await db_session.get(StoreDailyRecord, record.id) is None
    audit = await latest_audit(db_session, record.id)
    assert audit.operation_type == "delete"
    assert audit.before_json == expected
    assert audit.after_json is None
