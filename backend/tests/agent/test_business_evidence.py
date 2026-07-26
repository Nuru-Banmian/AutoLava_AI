from contextlib import asynccontextmanager
from datetime import datetime

import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.contracts import EvidencePlan
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags
from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord


def _monthly_total_plan() -> EvidencePlan:
    return EvidencePlan.model_validate(
        {
            "requests": [
                {
                    "kind": "business_metrics",
                    "metric": "monthly_total_revenue",
                }
            ]
        }
    )


def _context(store: Store) -> RuntimeContext:
    return RuntimeContext(
        user_id=1,
        store_id=store.id,
        role="admin",
        store_timezone=store.timezone,
        features=RuntimeFeatureFlags(
            agent_enabled=True,
            company_settlement_enabled=False,
            income_items_enabled=False,
            wash_count_enabled=True,
        ),
    )


async def test_collector_defaults_to_store_current_month_and_reconciles_total_revenue(
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="collector", password="secret", role="admin")
    store = await store_factory(name="Roma", timezone="Europe/Rome")
    db_session.add_all(
        [
            StoreDailyRecord(
                store_id=store.id,
                date=datetime(2026, 7, 1).date(),
                daily_revenue=125,
                income_mode="legacy_total",
                wash_count=2,
                is_open="营业",
                weather=None,
                weather_auto=None,
                weather_code=None,
                temperature_max=None,
                temperature_min=None,
                precipitation=None,
                activity=None,
                weather_edited=False,
                scanned=False,
                created_by=user.id,
                updated_by=user.id,
            ),
            StoreDailyRecord(
                store_id=store.id,
                date=datetime(2026, 7, 20).date(),
                daily_revenue=75,
                income_mode="legacy_total",
                wash_count=1,
                is_open="提前休息",
                weather=None,
                weather_auto=None,
                weather_code=None,
                temperature_max=None,
                temperature_min=None,
                precipitation=None,
                activity=None,
                weather_edited=False,
                scanned=False,
                created_by=user.id,
                updated_by=user.id,
            ),
        ]
    )
    await db_session.flush()
    company = SettlementCompany(
        store_id=store.id,
        name="Acme",
        normalized_name="acme",
        is_active=True,
        archived_at=None,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(company)
    await db_session.flush()
    db_session.add_all(
        [
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=datetime(2026, 7, 1).date(),
                amount=300,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=datetime(2026, 7, 1).date(),
                amount=900,
                status="pending",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=datetime(2026, 6, 1).date(),
                amount=700,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
        ]
    )
    await db_session.flush()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    collector = BusinessEvidenceCollector(
        session_factory,
        now=lambda _timezone: datetime(2026, 7, 26, 12, 0),
    )
    bundle = await collector.collect(
        _monthly_total_plan(),
        _context(store),
    )

    payload = bundle.model_dump(mode="json")
    assert payload["status"] == "ok"
    assert payload["current_store"] == {"id": store.id}
    assert payload["period"] == {"start": "2026-07-01", "end": "2026-07-26"}
    assert payload["metric"] == "monthly_total_revenue"
    assert payload["unit"] == "EUR"
    assert payload["calculation_version"] == "monthly_total_revenue.v1"
    assert payload["result"] == {
        "daily_ledger_revenue": 200,
        "confirmed_settlement_income": 300,
        "monthly_total_revenue": 500,
    }
    assert payload["coverage"] == {
        "calendar_dates": 26,
        "recorded_dates": 2,
        "operating_days": 2,
        "weather_recorded_dates": 0,
        "wash_count_enabled": True,
        "wash_count_recorded_operating_days": 2,
        "wash_count_missing_operating_days": 0,
        "wash_count_coverage_percent": 100,
        "wash_count_sufficient": True,
    }
    assert payload["completeness"]["status"] == "limited"
    assert len(payload["completeness"]["unrecorded_dates"]) == 24
    assert payload["completeness"]["missing_weather_dates"] == [
        "2026-07-01",
        "2026-07-20",
    ]
    assert payload["completeness"]["wash_count_missing_dates"] == []
    assert payload["completeness"]["category_total_mismatches"] == []
    assert payload["comparison"] is None
    assert payload["truncated"] is False
    assert "不推断记录起始日期" in payload["summary"]
    assert "缺少记录天气" in payload["summary"]


async def test_collector_retries_the_whole_snapshot_once_after_temporary_sqlite_failure(
    db_session: AsyncSession,
    store_factory,
) -> None:
    store = await store_factory(name="Retry", timezone="Europe/Rome")
    attempts = 0

    class FailingSession:
        async def execute(self, _statement):
            raise OperationalError("SELECT", {}, Exception("database is locked"))

    @asynccontextmanager
    async def session_factory():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            yield FailingSession()
        else:
            yield db_session

    bundle = await BusinessEvidenceCollector(
        session_factory,
        now=lambda _timezone: datetime(2026, 7, 26, 12, 0),
    ).collect(
        _monthly_total_plan(),
        _context(store),
    )

    assert attempts == 2
    assert bundle.result.monthly_total_revenue == 0


async def test_collector_discards_the_batch_after_a_second_sqlite_failure(
    store_factory,
) -> None:
    store = await store_factory(name="Failure", timezone="Europe/Rome")
    attempts = 0

    class FailingSession:
        async def execute(self, _statement):
            raise OperationalError("SELECT", {}, Exception("database is locked"))

    @asynccontextmanager
    async def session_factory():
        nonlocal attempts
        attempts += 1
        yield FailingSession()

    with pytest.raises(OperationalError):
        await BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 26, 12, 0),
        ).collect(
            _monthly_total_plan(),
            _context(store),
        )

    assert attempts == 2
