import asyncio
from copy import deepcopy
from dataclasses import dataclass
from datetime import date, datetime, timedelta
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
from app.models.income_config import IncomeConfigVersion, IncomeConfigVersionItem
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
    config: IncomeConfigVersion


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
    config = IncomeConfigVersion(
        store_id=store.id,
        version=1,
        enabled=True,
        created_by=user.id,
        items=[
            IncomeConfigVersionItem(
                category_id=category.id,
                name=category.name,
                include_in_total=True,
                is_active=True,
                sort_order=category.sort_order,
            )
            for category in (cash, card)
        ],
    )
    db_session.add(config)
    await db_session.flush()
    return RollbackContext(user=user, store=store, cash=cash, card=card, config=config)


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
        "config_version_id": context.config.id,
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
        payload=payload(context, "1.23", "4.56") | {"expected_version": 1},
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
    expected["row_version"] = 3

    restored = await rollback_service.rollback(update_audit.id, actor_id=rollback_context.user.id)

    assert restored is not None
    assert record_snapshot(restored) == expected
    assert rollback_service.last_event is not None
    assert rollback_service.last_event.operation == "rolled_back"
    assert rollback_service.last_event.row_version == 3
    rollback_audit = await latest_audit(db_session, operation_type="rollback")
    assert rollback_audit.store_id == rollback_context.store.id
    assert rollback_audit.record_id == restored.id
    assert rollback_audit.record_date == restored.date
    assert rollback_audit.operator_user_id == rollback_context.user.id
    assert rollback_audit.operation_source == "manual"
    assert rollback_audit.description == f"Rollback audit {update_audit.id}"
    assert rollback_audit.rollback_of_audit_id == update_audit.id
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
    expected["row_version"] = 2
    await ledger.delete(
        store=rollback_context.store,
        record_date=record.date,
        actor=rollback_context.user,
        expected_version=1,
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
            .where(AuditLog.rollback_of_audit_id == audit_id)
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
        payload=payload(rollback_context, "333.33", "0.00")
        | {"expected_version": 2},
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
            .where(AuditLog.rollback_of_audit_id == audit_id)
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
    updated_snapshot["row_version"] = 4
    await rollback_service.rollback(update_audit.id, actor_id=rollback_context.user.id)
    first_rollback = await latest_audit(db_session, operation_type="rollback")

    restored = await rollback_service.rollback(first_rollback.id, actor_id=rollback_context.user.id)

    assert restored is not None
    assert record_snapshot(restored) == updated_snapshot
    with pytest.raises(HTTPException) as exc_info:
        await rollback_service.rollback(first_rollback.id, actor_id=rollback_context.user.id)
    assert exc_info.value.status_code == 409


async def _make_equal_timestamp_update(
    session: AsyncSession,
    context: RollbackContext,
    *,
    current_is_after: bool,
) -> tuple[StoreDailyRecord, AuditLog, dict, dict]:
    cash_amount = "50.00" if current_is_after else "10.00"
    record, _ = await LedgerService(session).upsert(
        store=context.store,
        record_date=local_today(context),
        payload=payload(context, cash_amount, "20.00"),
        actor=context.user,
    )
    fixed_updated_at = datetime(2020, 1, 2, 3, 4, 5)
    record.updated_at = fixed_updated_at
    await session.flush()
    await session.refresh(record, attribute_names=["updated_at", "items"])

    current = record_snapshot(record)
    alternate = deepcopy(current)
    alternate["daily_revenue"] = "30.00" if current_is_after else "70.00"
    alternate["items"][0]["amount"] = "10.00" if current_is_after else "50.00"
    before, after = (alternate, current) if current_is_after else (current, alternate)
    update_audit = AuditLog(
        operation_domain="ledger",
        store_id=record.store_id,
        record_id=record.id,
        record_date=record.date,
        operation_type="update",
        operation_source="manual",
        operator_user_id=context.user.id,
        before_json=before,
        after_json=after,
        description="Equal-timestamp ledger update",
        requires_approval=False,
        approved=True,
    )
    session.add(update_audit)
    await session.flush()
    return record, update_audit, before, after


async def test_rollback_explicitly_restores_equal_parent_updated_at(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    _, update_audit, before, _ = await _make_equal_timestamp_update(
        db_session,
        rollback_context,
        current_is_after=True,
    )

    restored = await rollback_service.rollback(
        update_audit.id,
        actor_id=rollback_context.user.id,
    )

    assert restored is not None
    assert record_snapshot(restored) == before | {"row_version": 2}


async def test_rollback_chain_explicitly_restores_equal_parent_updated_at(
    rollback_service: RollbackService,
    rollback_context: RollbackContext,
    db_session: AsyncSession,
) -> None:
    record, update_audit, before, after = await _make_equal_timestamp_update(
        db_session,
        rollback_context,
        current_is_after=False,
    )
    first_rollback = AuditLog(
        operation_domain="ledger",
        store_id=record.store_id,
        record_id=record.id,
        record_date=record.date,
        operation_type="rollback",
        operation_source="manual",
        operator_user_id=rollback_context.user.id,
        before_json=after,
        after_json=before,
        description=f"Rollback audit {update_audit.id}",
        requires_approval=False,
        approved=True,
        rollback_of_audit_id=update_audit.id,
    )
    db_session.add(first_rollback)
    await db_session.flush()

    restored = await rollback_service.rollback(
        first_rollback.id,
        actor_id=rollback_context.user.id,
    )

    assert restored is not None
    assert record_snapshot(restored) == after | {"row_version": 2}


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
        config = IncomeConfigVersion(
            store_id=store.id,
            version=1,
            enabled=True,
            created_by=user.id,
            items=[
                IncomeConfigVersionItem(
                    category_id=category.id,
                    name=category.name,
                    include_in_total=True,
                    is_active=True,
                    sort_order=category.sort_order,
                )
                for category in (cash, card)
            ],
        )
        session.add(config)
        await session.flush()
        context = RollbackContext(
            user=user, store=store, cash=cash, card=card, config=config
        )
        _, update_audit = await make_update(session, context)
        expected = deepcopy(update_audit.before_json)
        expected["row_version"] = 3
        return (
            user.id,
            store.id,
            cash.id,
            card.id,
            update_audit.id,
            expected,
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
                    .where(AuditLog.rollback_of_audit_id == audit_id)
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


class _TwoPartyBarrier:
    def __init__(self) -> None:
        self.arrivals = 0
        self.ready = asyncio.Event()

    async def wait(self) -> None:
        self.arrivals += 1
        if self.arrivals == 2:
            self.ready.set()
        await asyncio.wait_for(self.ready.wait(), timeout=5)


class _CoordinatedRollbackService(RollbackService):
    def __init__(self, session: AsyncSession, barrier: _TwoPartyBarrier):
        super().__init__(session)
        self.barrier = barrier

    async def _lock_audit(self, audit_id: int) -> AuditLog:
        audit = await super()._lock_audit(audit_id)
        await self.barrier.wait()
        return audit


async def test_different_audit_rollbacks_do_not_lock_each_others_target_rows() -> None:
    await _clear_disposable_database()
    maker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        user_id, store_id, cash_id, card_id, first_audit_id, _ = await _committed_update_fixture()
        async with maker() as setup_session:
            store = await setup_session.get(Store, store_id)
            user = await setup_session.get(User, user_id)
            cash = await setup_session.get(IncomeCategory, cash_id)
            card = await setup_session.get(IncomeCategory, card_id)
            config = await setup_session.scalar(
                select(IncomeConfigVersion).where(
                    IncomeConfigVersion.store_id == store_id
                )
            )
            assert store is not None and user is not None and cash is not None and card is not None
            assert config is not None
            context = RollbackContext(
                user=user, store=store, cash=cash, card=card, config=config
            )
            second_date = local_today(context) - timedelta(days=1)
            await LedgerService(setup_session).upsert(
                store=store,
                record_date=second_date,
                payload=payload(context, "80.00", "20.00"),
                actor=user,
            )
            await LedgerService(setup_session).upsert(
                store=store,
                record_date=second_date,
                    payload=payload(context, "70.00", "10.00")
                    | {"expected_version": 1},
                actor=user,
                overwrite=True,
            )
            second_audit_id = await setup_session.scalar(
                select(AuditLog.id)
                .where(
                    AuditLog.operation_type == "update",
                    AuditLog.record_date == second_date,
                )
                .order_by(AuditLog.id.desc())
            )
            assert second_audit_id is not None

        barrier = _TwoPartyBarrier()

        async def attempt(audit_id: int) -> StoreDailyRecord | None:
            async with maker() as session:
                return await _CoordinatedRollbackService(session, barrier).rollback(
                    audit_id, actor_id=user_id
                )

        first_result, second_result = await asyncio.wait_for(
            asyncio.gather(attempt(first_audit_id), attempt(second_audit_id)),
            timeout=10,
        )

        assert first_result is not None
        assert second_result is not None
        async with maker() as check_session:
            rollback_targets = set(
                await check_session.scalars(
                    select(AuditLog.rollback_of_audit_id).where(
                        AuditLog.rollback_of_audit_id.in_([first_audit_id, second_audit_id])
                    )
                )
            )
        assert rollback_targets == {first_audit_id, second_audit_id}
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
                config = await session.scalar(
                    select(IncomeConfigVersion).where(
                        IncomeConfigVersion.store_id == store_id
                    )
                )
                assert (
                    store is not None
                    and user is not None
                    and cash is not None
                    and card is not None
                    and config is not None
                )
                context = RollbackContext(
                    user=user, store=store, cash=cash, card=card, config=config
                )
                await start.wait()
                return await LedgerService(session).upsert(
                    store=store,
                    record_date=local_today(context),
                    payload=payload(context, "333.33", "0.00")
                    | {"expected_version": 3},
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
                    .where(AuditLog.rollback_of_audit_id == audit_id)
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
                .where(AuditLog.rollback_of_audit_id == audit_id)
            )

        assert response.status_code == 409
        assert response.json() == {"detail": "Audit entry already rolled back"}
        assert marker_count == 1
    finally:
        await _clear_disposable_database()
        await engine.dispose()
