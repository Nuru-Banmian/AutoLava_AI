from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.income_config import IncomeConfigVersion
from app.services.retention import RetentionResult, RetentionService


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)


def _audit(*, store_id: int, user_id: int, record_id: int, created_at: datetime) -> AuditLog:
    return AuditLog(
        operation_domain="ledger",
        store_id=store_id,
        record_id=record_id,
        record_date=created_at.date(),
        operation_type="update",
        operation_source="manual",
        operator_user_id=user_id,
        before_json={"state": "before"},
        after_json={"state": "after"},
        description=f"Ledger change for record {record_id}",
        requires_approval=False,
        approved=True,
        rollbackable=True,
        created_at=created_at,
    )


async def test_prune_caps_ledger_snapshots_per_record_and_keeps_metadata(
    db_session, store_factory, user_factory
) -> None:
    store = await store_factory(name="Retention ledger")
    actor = await user_factory(username="retention-ledger", password="secret")
    naive_now = NOW.replace(tzinfo=None)
    record_one = [
        _audit(
            store_id=store.id,
            user_id=actor.id,
            record_id=101,
            created_at=naive_now - timedelta(days=index),
        )
        for index in range(12)
    ]
    record_two_recent = _audit(
        store_id=store.id,
        user_id=actor.id,
        record_id=202,
        created_at=naive_now - timedelta(days=364),
    )
    record_two_expired = _audit(
        store_id=store.id,
        user_id=actor.id,
        record_id=202,
        created_at=naive_now - timedelta(days=366),
    )
    unrelated = _audit(
        store_id=store.id,
        user_id=actor.id,
        record_id=303,
        created_at=naive_now - timedelta(days=500),
    )
    unrelated.operation_domain = "admin"
    unrelated.description = "Unrelated admin metadata"
    db_session.add_all(record_one + [record_two_recent, record_two_expired, unrelated])
    await db_session.flush()

    result = await RetentionService(db_session).prune(now=NOW)

    assert result == RetentionResult(ledger_snapshots_pruned=3, config_versions_pruned=0)
    rows = list(await db_session.scalars(select(AuditLog).order_by(AuditLog.id)))
    record_one_rows = [row for row in rows if row.record_id == 101]
    assert sum(row.rollbackable for row in record_one_rows) == 10
    assert record_one[-1].rollbackable is False
    assert record_one[-2].rollbackable is False
    assert record_two_recent.rollbackable is True
    assert record_two_expired.rollbackable is False
    for row in (record_one[-1], record_one[-2], record_two_expired):
        assert row.before_json is None
        assert row.after_json is None
        assert row.snapshot_expires_at == naive_now
        assert row.description
        assert row.store_id == store.id
        assert row.operator_user_id == actor.id
    assert unrelated.rollbackable is True
    assert unrelated.before_json == {"state": "before"}

    assert await RetentionService(db_session).prune(now=NOW) == RetentionResult(
        ledger_snapshots_pruned=0,
        config_versions_pruned=0,
    )


async def test_prune_caps_config_versions_per_store_and_never_deletes_latest(
    db_session, store_factory, user_factory
) -> None:
    actor = await user_factory(username="retention-config", password="secret")
    capped_store = await store_factory(name="Capped config")
    expired_store = await store_factory(name="Expired config")
    naive_now = NOW.replace(tzinfo=None)
    capped = [
        IncomeConfigVersion(
            store_id=capped_store.id,
            version=version,
            enabled=version == 22,
            created_by=actor.id,
            created_at=naive_now - timedelta(days=version),
        )
        for version in range(1, 23)
    ]
    expired = [
        IncomeConfigVersion(
            store_id=expired_store.id,
            version=version,
            enabled=version == 3,
            created_by=actor.id,
            created_at=naive_now - timedelta(days=200 + version),
        )
        for version in range(1, 4)
    ]
    db_session.add_all(capped + expired)
    await db_session.flush()

    result = await RetentionService(db_session).prune(now=NOW)

    assert result == RetentionResult(ledger_snapshots_pruned=0, config_versions_pruned=4)
    capped_versions = list(
        await db_session.scalars(
            select(IncomeConfigVersion.version)
            .where(IncomeConfigVersion.store_id == capped_store.id)
            .order_by(IncomeConfigVersion.version.desc())
        )
    )
    expired_versions = list(
        await db_session.scalars(
            select(IncomeConfigVersion.version)
            .where(IncomeConfigVersion.store_id == expired_store.id)
            .order_by(IncomeConfigVersion.version.desc())
        )
    )
    assert capped_versions == list(range(22, 2, -1))
    assert expired_versions == [3]

    assert await RetentionService(db_session).prune(now=NOW) == RetentionResult(
        ledger_snapshots_pruned=0,
        config_versions_pruned=0,
    )
