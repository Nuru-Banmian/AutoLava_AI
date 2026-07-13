import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest
from fastapi import HTTPException
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from app.core.database import engine, get_session
from app.core.security import create_access_token
from app.main import create_app
from app.models.audit import AuditLog
from app.models.base import Base
from app.models.identity import Store, StoreMember, User
from app.models.ledger import IncomeCategory, StoreDailyRecord
from app.services.audit import record_snapshot
from app.services.ledger import LedgerService
from app.services.rollback import RollbackService


@dataclass
class RollbackContext:
    user: User
    store: Store
    cash: IncomeCategory
    card: IncomeCategory


@pytest.fixture
async def rollback_context(db_session, user_factory, store_factory) -> RollbackContext:
    user = await user_factory(username="rollback-user", password="secret")
    store = await store_factory(name="Rollback Store", timezone="Europe/Berlin")
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
    db_session.add_all([cash, card])
    await db_session.flush()
    return RollbackContext(user=user, store=store, cash=cash, card=card)


@pytest.fixture
def rollback_service(db_session: AsyncSession) -> RollbackService:
    return RollbackService(db_session)


def local_today(context: RollbackContext) -> date:
    return datetime.now(ZoneInfo(context.store.timezone)).date()


def payload(context: RollbackContext, cash: str, card: str) -> dict:
    return {
        "is_open": "营业",
        "wash_count": 12,
        "weather": "晴",
        "weather_edited": True,
        "activity": "rollback test",
        "items": [
            {"category_id": context.cash.id, "amount": cash},
            {"category_id": context.card.id, "amount": card},
        ],
    }


async def latest_audit(session: AsyncSession, *, operation_type: str | None = None) -> AuditLog:
    query = select(AuditLog).where(AuditLog.operation_domain == "ledger")
    if operation_type is not None:
        query = query.where(AuditLog.operation_type == operation_type)
    audit = await session.scalar(query.order_by(AuditLog.id.desc()).limit(1))
    assert audit is not None
    return audit


async def make_update(
    session: AsyncSession, context: RollbackContext
) -> tuple[StoreDailyRecord, AuditLog]:
    ledger = LedgerService(session)
    record, _ = await ledger.upsert(
        store=context.store,
        record_date=local_today(context),
        payload=payload(context, "100.01", "50.02"),
        actor=context.user,
    )
    await ledger.upsert(
        store=context.store,
        record_date=local_today(context),
        payload=payload(context, "1.23", "4.56"),
        actor=context.user,
        overwrite=True,
    )
    return record, await latest_audit(session, operation_type="update")


async def test_rollback_update_restores_exact_canonical_before_snapshot(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    _, update_audit = await make_update(db_session, rollback_context)
    expected = deepcopy(update_audit.before_json)

    restored = await rollback_service.rollback(update_audit.id, actor_id=rollback_context.user.id)

    assert restored is not None
    assert record_snapshot(restored) == expected
    rollback_audit = await latest_audit(db_session, operation_type="rollback")
    assert rollback_audit.store_id == rollback_context.store.id
    assert rollback_audit.record_id == restored.id
    assert rollback_audit.record_date == restored.date
    assert rollback_audit.operator_user_id == rollback_context.user.id
    assert rollback_audit.operation_source == "manual"
    assert rollback_audit.description == f"Rollback audit {update_audit.id}"
    assert rollback_audit.before_json == update_audit.after_json
    assert rollback_audit.after_json == expected
    assert rollback_audit.requires_approval is False
    assert rollback_audit.approved is True


async def test_rollback_delete_recreates_record_items_ids_and_timestamps(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    ledger = LedgerService(db_session)
    record, _ = await ledger.upsert(
        store=rollback_context.store,
        record_date=local_today(rollback_context),
        payload=payload(rollback_context, "0.01", "9999999999.98"),
        actor=rollback_context.user,
    )
    expected = record_snapshot(record)
    await ledger.delete(
        store=rollback_context.store,
        record_date=record.date,
        actor=rollback_context.user,
    )
    delete_audit = await latest_audit(db_session, operation_type="delete")

    restored = await rollback_service.rollback(delete_audit.id, actor_id=rollback_context.user.id)

    assert restored is not None
    assert record_snapshot(restored) == expected
    assert restored.daily_revenue == Decimal("9999999999.99")
    assert [item.id for item in restored.items] == [item["id"] for item in expected["items"]]


async def test_rollback_create_deletes_record_and_audits_complete_before_state(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    record, _ = await LedgerService(db_session).upsert(
        store=rollback_context.store,
        record_date=local_today(rollback_context),
        payload=payload(rollback_context, "10.00", "20.00"),
        actor=rollback_context.user,
    )
    create_audit = await latest_audit(db_session, operation_type="create")
    expected_before = deepcopy(create_audit.after_json)

    restored = await rollback_service.rollback(create_audit.id, actor_id=rollback_context.user.id)

    assert restored is None
    assert await db_session.get(StoreDailyRecord, record.id) is None
    rollback_audit = await latest_audit(db_session, operation_type="rollback")
    assert rollback_audit.record_id == record.id
    assert rollback_audit.before_json == expected_before
    assert rollback_audit.after_json is None


async def test_same_audit_cannot_be_rolled_back_twice(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    _, update_audit = await make_update(db_session, rollback_context)
    audit_id = update_audit.id
    actor_id = rollback_context.user.id
    await rollback_service.rollback(audit_id, actor_id=actor_id)

    with pytest.raises(HTTPException) as exc_info:
        await rollback_service.rollback(audit_id, actor_id=actor_id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Audit entry already rolled back"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.operation_type == "rollback",
                AuditLog.description == f"Rollback audit {audit_id}",
            )
        )
        == 1
    )


async def test_rollback_refuses_to_overwrite_a_later_change_without_partial_writes(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    record, update_audit = await make_update(db_session, rollback_context)
    audit_id = update_audit.id
    actor_id = rollback_context.user.id
    store_id = rollback_context.store.id
    record_date = record.date
    later, _ = await LedgerService(db_session).upsert(
        store=rollback_context.store,
        record_date=record.date,
        payload=payload(rollback_context, "333.33", "0.00"),
        actor=rollback_context.user,
        overwrite=True,
    )
    expected = record_snapshot(later)

    with pytest.raises(HTTPException) as exc_info:
        await rollback_service.rollback(audit_id, actor_id=actor_id)

    assert exc_info.value.status_code == 409
    assert exc_info.value.detail == "Record changed after this audit entry"
    current = await db_session.scalar(
        select(StoreDailyRecord)
        .where(
            StoreDailyRecord.store_id == store_id,
            StoreDailyRecord.date == record_date,
        )
        .options(selectinload(StoreDailyRecord.items))
    )
    assert record_snapshot(current) == expected
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(
                AuditLog.operation_type == "rollback",
                AuditLog.description == f"Rollback audit {audit_id}",
            )
        )
        == 0
    )


async def test_rollback_audit_can_be_reversed_as_a_chain_but_not_reused(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    _, update_audit = await make_update(db_session, rollback_context)
    updated_snapshot = deepcopy(update_audit.after_json)
    await rollback_service.rollback(update_audit.id, actor_id=rollback_context.user.id)
    first_rollback = await latest_audit(db_session, operation_type="rollback")

    restored = await rollback_service.rollback(first_rollback.id, actor_id=rollback_context.user.id)

    assert restored is not None
    assert record_snapshot(restored) == updated_snapshot
    with pytest.raises(HTTPException) as exc_info:
        await rollback_service.rollback(first_rollback.id, actor_id=rollback_context.user.id)
    assert exc_info.value.status_code == 409


async def test_missing_or_non_ledger_audit_is_not_rollbackable(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    admin_audit = AuditLog(
        operation_domain="admin",
        store_id=rollback_context.store.id,
        record_id=rollback_context.store.id,
        record_date=None,
        operation_type="update",
        operation_source="manual",
        operator_user_id=rollback_context.user.id,
        before_json=None,
        after_json=None,
        description="not ledger",
        requires_approval=False,
        approved=True,
    )
    db_session.add(admin_audit)
    await db_session.flush()

    for audit_id in (admin_audit.id, 999999):
        with pytest.raises(HTTPException) as exc_info:
            await rollback_service.rollback(audit_id, actor_id=rollback_context.user.id)
        assert exc_info.value.status_code == 404
        assert exc_info.value.detail == "Audit entry not found"


async def _clear_disposable_database() -> None:
    if engine.dialect.name != "mysql" or engine.url.database != "autolava_test":
        raise RuntimeError("Rollback race tests require the dedicated MySQL autolava_test database")
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())


async def _committed_update_fixture() -> tuple[int, int, int, int, int, dict]:
    maker = async_sessionmaker(engine, expire_on_commit=False)
    async with maker() as session:
        user = User(
            username="rollback-race-user",
            password_hash="test-only",
            role="user",
            is_active=True,
            remember_token=None,
        )
        store = Store(
            name="Rollback race store",
            address="Race address",
            latitude=Decimal("45.000000"),
            longitude=Decimal("9.000000"),
            timezone="Europe/Berlin",
            is_active=True,
        )
        session.add_all([user, store])
        await session.flush()
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
        session.add_all([cash, card])
        await session.flush()
        context = RollbackContext(user=user, store=store, cash=cash, card=card)
        _, update_audit = await make_update(session, context)
        return (
            user.id,
            store.id,
            cash.id,
            card.id,
            update_audit.id,
            deepcopy(update_audit.before_json),
        )


async def test_concurrent_same_audit_rollback_serializes_to_one_success() -> None:
    await _clear_disposable_database()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        user_id, _, _, _, audit_id, expected = await _committed_update_fixture()
        start = asyncio.Event()

        async def attempt() -> StoreDailyRecord | None:
            async with maker() as session:
                await start.wait()
                return await RollbackService(session).rollback(audit_id, actor_id=user_id)

        tasks = [asyncio.create_task(attempt()), asyncio.create_task(attempt())]
        start.set()
        results = await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), timeout=10)

        successes = [value for value in results if isinstance(value, StoreDailyRecord)]
        conflicts = [value for value in results if isinstance(value, HTTPException)]
        assert len(successes) == 1
        assert len(conflicts) == 1
        assert conflicts[0].status_code == 409
        async with maker() as session:
            assert (
                await session.scalar(
                    select(func.count())
                    .select_from(AuditLog)
                    .where(
                        AuditLog.operation_type == "rollback",
                        AuditLog.description == f"Rollback audit {audit_id}",
                    )
                )
                == 1
            )
            current = await session.get(StoreDailyRecord, expected["id"])
            assert current is not None
            await session.refresh(current, attribute_names=["items"])
            assert record_snapshot(current) == expected
    finally:
        await _clear_disposable_database()
        await engine.dispose()


async def test_concurrent_later_update_is_never_lost_inside_rollback_window() -> None:
    await _clear_disposable_database()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        user_id, store_id, cash_id, card_id, audit_id, _ = await _committed_update_fixture()
        start = asyncio.Event()

        async def attempt_rollback():
            async with maker() as session:
                await start.wait()
                return await RollbackService(session).rollback(audit_id, actor_id=user_id)

        async def later_update():
            async with maker() as session:
                store = await session.get(Store, store_id)
                user = await session.get(User, user_id)
                cash = await session.get(IncomeCategory, cash_id)
                card = await session.get(IncomeCategory, card_id)
                assert (
                    store is not None and user is not None and cash is not None and card is not None
                )
                context = RollbackContext(user=user, store=store, cash=cash, card=card)
                await start.wait()
                return await LedgerService(session).upsert(
                    store=store,
                    record_date=local_today(context),
                    payload=payload(context, "333.33", "0.00"),
                    actor=user,
                    overwrite=True,
                )

        rollback_task = asyncio.create_task(attempt_rollback())
        update_task = asyncio.create_task(later_update())
        start.set()
        rollback_result, update_result = await asyncio.wait_for(
            asyncio.gather(rollback_task, update_task, return_exceptions=True), timeout=10
        )

        assert not isinstance(update_result, BaseException)
        assert isinstance(rollback_result, (StoreDailyRecord, HTTPException))
        if isinstance(rollback_result, HTTPException):
            assert rollback_result.status_code == 409
            assert rollback_result.detail == "Record changed after this audit entry"
        async with maker() as session:
            current = await session.scalar(
                select(StoreDailyRecord).where(StoreDailyRecord.store_id == store_id)
            )
            assert current is not None
            await session.refresh(current, attribute_names=["items"])
            assert current.daily_revenue == Decimal("333.33")
            assert {item.amount for item in current.items} == {
                Decimal("333.33"),
                Decimal("0.00"),
            }
    finally:
        await _clear_disposable_database()
        await engine.dispose()


async def test_api_rollback_sees_marker_committed_after_its_dependency_snapshot() -> None:
    await _clear_disposable_database()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        user_id, store_id, _, _, audit_id, _ = await _committed_update_fixture()
        async with maker() as setup_session:
            setup_session.add(StoreMember(store_id=store_id, user_id=user_id))
            await setup_session.commit()

        async with maker() as request_session:
            # This is the first plain dependency-style read and establishes the
            # InnoDB REPEATABLE READ snapshot before either rollback marker exists.
            assert await request_session.get(User, user_id) is not None

            async with maker() as chain_session:
                await RollbackService(chain_session).rollback(audit_id, actor_id=user_id)
                first_rollback_id = await chain_session.scalar(
                    select(AuditLog.id)
                    .where(
                        AuditLog.operation_type == "rollback",
                        AuditLog.description == f"Rollback audit {audit_id}",
                    )
                    .order_by(AuditLog.id.desc())
                )
                assert first_rollback_id is not None
                await RollbackService(chain_session).rollback(first_rollback_id, actor_id=user_id)

            app = create_app()

            async def override_session():
                yield request_session

            app.dependency_overrides[get_session] = override_session
            token, _ = create_access_token(user_id, remember=False)
            async with AsyncClient(
                transport=ASGITransport(app=app), base_url="http://testserver"
            ) as client:
                client.cookies.set("access_token", token)
                response = await client.post(
                    f"/api/database/{store_id}/history/{audit_id}/rollback"
                )

        async with maker() as check_session:
            marker_count = await check_session.scalar(
                select(func.count())
                .select_from(AuditLog)
                .where(
                    AuditLog.operation_type == "rollback",
                    AuditLog.description == f"Rollback audit {audit_id}",
                )
            )

        assert response.status_code == 409
        assert response.json() == {"detail": "Audit entry already rolled back"}
        assert marker_count == 1
    finally:
        await _clear_disposable_database()
        await engine.dispose()
