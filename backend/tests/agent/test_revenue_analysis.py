from contextlib import asynccontextmanager
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.business_evidence import BusinessEvidenceCollector
from app.agent.contracts import EvidencePlan
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags
from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord


def _context(store: Store) -> RuntimeContext:
    return RuntimeContext(
        user_id=1,
        store_id=store.id,
        role="admin",
        store_timezone=store.timezone,
        features=RuntimeFeatureFlags(
            agent_enabled=True,
            company_settlement_enabled=True,
            income_items_enabled=False,
            wash_count_enabled=True,
        ),
    )


def _analysis_plan(*, include_percentage: bool = False) -> EvidencePlan:
    return EvidencePlan.model_validate(
        {
            "requests": [
                {
                    "kind": "revenue_analysis",
                    "include_percentage": include_percentage,
                }
            ]
        }
    )


async def _record(
    session: AsyncSession,
    *,
    store_id: int,
    user_id: int,
    on: date,
    revenue: int,
    wash_count: int | None = 1,
    operating_status: str = "营业",
    income_mode: str = "legacy_total",
) -> StoreDailyRecord:
    record = StoreDailyRecord(
        store_id=store_id,
        date=on,
        daily_revenue=revenue,
        income_mode=income_mode,
        wash_count=wash_count,
        is_open=operating_status,
        weather="晴",
        weather_auto=None,
        weather_code=None,
        temperature_max=None,
        temperature_min=None,
        precipitation=None,
        activity=None,
        weather_edited=False,
        scanned=False,
        created_by=user_id,
        updated_by=user_id,
    )
    session.add(record)
    await session.flush()
    return record


async def test_revenue_analysis_reconciles_symmetric_and_settlement_contributions(
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="analysis", password="secret", role="admin")
    store = await store_factory(name="Analysis")
    # Previous month: 2 operating days * EUR 100 = EUR 200.
    await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 6, 1),
        revenue=100,
    )
    await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 6, 2),
        revenue=100,
    )
    # Current month: 3 operating days * EUR 120 = EUR 360.
    for day in (1, 2, 3):
        await _record(
            db_session,
            store_id=store.id,
            user_id=user.id,
            on=date(2026, 7, day),
            revenue=120,
        )
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
                opening_month=date(2026, 6, 1),
                amount=100,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=140,
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

    bundle = await BusinessEvidenceCollector(
        session_factory,
        now=lambda _timezone: datetime(2026, 7, 3, 12, 0),
    ).collect(_analysis_plan(), _context(store))
    payload = bundle.model_dump(mode="json")

    assert payload["period"] == {"start": "2026-07-01", "end": "2026-07-03"}
    assert payload["comparison_period"] == {
        "start": "2026-06-01",
        "end": "2026-06-30",
    }
    assert payload["result"]["total_revenue_change"] == 200
    assert payload["result"]["daily_ledger_revenue_change"] == 160
    assert payload["result"]["confirmed_settlement_income_change"] == 40
    decomposition = payload["result"]["daily_ledger_decomposition"]
    assert Decimal(decomposition["operating_days_contribution"]) == Decimal("110")
    assert Decimal(decomposition["operating_day_average_contribution"]) == Decimal("50")
    assert (
        Decimal(decomposition["operating_days_contribution"])
        + Decimal(decomposition["operating_day_average_contribution"])
        == Decimal(payload["result"]["daily_ledger_revenue_change"])
    )
    assert payload["evidence_sufficiency"] == {
        "critical_data_complete": True,
        "largest_verified_contribution": "operating_days",
        "largest_absolute_share": "0.55",
        "major_driver_threshold": "0.6",
        "allows_mainly_from": False,
    }
    assert payload["findings"]["unexplained_amount"] == "0"


@pytest.mark.parametrize(
    ("ledger_change", "settlement_change", "expected_share", "allowed"),
    [
        (60, 40, "0.6", True),
        (59, 41, "0.59", False),
    ],
)
async def test_revenue_analysis_enforces_major_driver_threshold_boundaries(
    db_session: AsyncSession,
    user_factory,
    store_factory,
    ledger_change: int,
    settlement_change: int,
    expected_share: str,
    allowed: bool,
) -> None:
    user = await user_factory(
        username=f"threshold-{ledger_change}",
        password="secret",
        role="admin",
    )
    store = await store_factory(name=f"Threshold {ledger_change}")
    await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 6, 1),
        revenue=100,
    )
    await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 7, 1),
        revenue=100 + ledger_change,
    )
    company = SettlementCompany(
        store_id=store.id,
        name="Threshold Co",
        normalized_name="threshold co",
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
                opening_month=date(2026, 6, 1),
                amount=100,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=100 + settlement_change,
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

    payload = (
        await BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 1, 12, 0),
        ).collect(_analysis_plan(), _context(store))
    ).model_dump(mode="json")

    assert payload["evidence_sufficiency"]["largest_absolute_share"] == expected_share
    assert payload["evidence_sufficiency"]["allows_mainly_from"] is allowed


async def test_revenue_analysis_handles_zero_baseline_and_unavailable_decomposition(
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="zero", password="secret", role="admin")
    store = await store_factory(name="Zero")
    await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 6, 1),
        revenue=0,
        operating_status="休息",
        wash_count=None,
    )
    await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 7, 1),
        revenue=100,
    )

    @asynccontextmanager
    async def session_factory():
        yield db_session

    payload = (
        await BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 1, 12, 0),
        ).collect(_analysis_plan(include_percentage=True), _context(store))
    ).model_dump(mode="json")

    assert payload["result"]["percentage_status"] == "unavailable_zero_baseline"
    assert payload["result"]["percentage_change"] is None
    assert payload["result"]["daily_ledger_decomposition"]["status"] == "unavailable"
    assert payload["findings"]["unexplained_amount"] == "100"
    assert payload["evidence_sufficiency"]["allows_mainly_from"] is False


async def test_revenue_analysis_reports_exact_category_and_other_data_changes(
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="categories", password="secret", role="admin")
    store = await store_factory(name="Categories")
    cash = IncomeCategory(
        store_id=store.id,
        name="现金",
        include_in_total=True,
        is_active=True,
        sort_order=1,
        archived_at=None,
    )
    other = IncomeCategory(
        store_id=store.id,
        name="代收款",
        include_in_total=False,
        is_active=True,
        sort_order=2,
        archived_at=None,
    )
    db_session.add_all([cash, other])
    await db_session.flush()
    previous = await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 6, 1),
        revenue=100,
        income_mode="composed",
    )
    current = await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 7, 1),
        revenue=130,
        income_mode="composed",
    )
    db_session.add_all(
        [
            DailyIncomeItem(
                record_id=previous.id,
                category_id=cash.id,
                category_name="现金",
                include_in_total=True,
                sort_order=1,
                amount=100,
            ),
            DailyIncomeItem(
                record_id=previous.id,
                category_id=other.id,
                category_name="代收款",
                include_in_total=False,
                sort_order=2,
                amount=15,
            ),
            DailyIncomeItem(
                record_id=current.id,
                category_id=cash.id,
                category_name="现金",
                include_in_total=True,
                sort_order=1,
                amount=130,
            ),
            DailyIncomeItem(
                record_id=current.id,
                category_id=other.id,
                category_name="代收款",
                include_in_total=False,
                sort_order=2,
                amount=5,
            ),
        ]
    )
    await db_session.flush()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    payload = (
        await BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 1, 12, 0),
        ).collect(_analysis_plan(), _context(store))
    ).model_dump(mode="json")

    assert payload["result"]["income_category_changes"] == [
        {
            "category_id": cash.id,
            "category_name": "现金",
            "current_amount": 130,
            "comparison_amount": 100,
            "amount_change": 30,
        }
    ]
    assert payload["result"]["other_data_changes"] == [
        {
            "category_id": other.id,
            "category_name": "代收款",
            "current_amount": 5,
            "comparison_amount": 15,
            "amount_change": -10,
        }
    ]


async def test_revenue_analysis_without_history_describes_only_current_period(
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="current-only", password="secret", role="admin")
    store = await store_factory(name="Current only")
    await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 7, 1),
        revenue=80,
    )

    @asynccontextmanager
    async def session_factory():
        yield db_session

    payload = (
        await BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 1, 12, 0),
        ).collect(_analysis_plan(), _context(store))
    ).model_dump(mode="json")

    assert payload["status"] == "current_only"
    assert payload["comparison_period"] is None
    assert payload["result"]["comparison"] is None
    assert payload["result"]["total_revenue_change"] is None
    assert "只描述当前期间" in payload["summary"]


async def test_revenue_analysis_does_not_decompose_with_critical_coverage_gap(
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(username="coverage-gap", password="secret", role="admin")
    store = await store_factory(name="Coverage gap")
    category = IncomeCategory(
        store_id=store.id,
        name="现金",
        include_in_total=True,
        is_active=True,
        sort_order=1,
        archived_at=None,
    )
    db_session.add(category)
    await db_session.flush()
    previous = await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 6, 1),
        revenue=100,
        income_mode="composed",
    )
    current = await _record(
        db_session,
        store_id=store.id,
        user_id=user.id,
        on=date(2026, 7, 1),
        revenue=150,
        income_mode="composed",
    )
    # The current included category sum does not reconcile to daily revenue.
    db_session.add_all(
        [
            DailyIncomeItem(
                record_id=previous.id,
                category_id=category.id,
                category_name="现金",
                include_in_total=True,
                sort_order=1,
                amount=100,
            ),
            DailyIncomeItem(
                record_id=current.id,
                category_id=category.id,
                category_name="现金",
                include_in_total=True,
                sort_order=1,
                amount=120,
            ),
        ]
    )
    await db_session.flush()

    @asynccontextmanager
    async def session_factory():
        yield db_session

    payload = (
        await BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 1, 12, 0),
        ).collect(_analysis_plan(), _context(store))
    ).model_dump(mode="json")

    assert payload["evidence_sufficiency"]["critical_data_complete"] is False
    assert payload["evidence_sufficiency"]["allows_mainly_from"] is False
    assert payload["result"]["daily_ledger_decomposition"]["status"] == "unavailable"
    assert payload["findings"]["unexplained_amount"] == "50"


async def test_revenue_analysis_can_identify_settlement_as_main_driver_without_operating_days(
    db_session: AsyncSession,
    user_factory,
    store_factory,
) -> None:
    user = await user_factory(
        username="settlement-driver",
        password="secret",
        role="admin",
    )
    store = await store_factory(name="Settlement driver")
    for on in (date(2026, 6, 1), date(2026, 7, 1)):
        await _record(
            db_session,
            store_id=store.id,
            user_id=user.id,
            on=on,
            revenue=0,
            operating_status="休息",
            wash_count=None,
        )
    company = SettlementCompany(
        store_id=store.id,
        name="Settlement Co",
        normalized_name="settlement co",
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
                opening_month=date(2026, 6, 1),
                amount=100,
                status="confirmed",
                created_by=user.id,
                updated_by=user.id,
            ),
            SettlementRecord(
                store_id=store.id,
                company_id=company.id,
                company_name=company.name,
                opening_month=date(2026, 7, 1),
                amount=200,
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

    payload = (
        await BusinessEvidenceCollector(
            session_factory,
            now=lambda _timezone: datetime(2026, 7, 1, 12, 0),
        ).collect(_analysis_plan(include_percentage=True), _context(store))
    ).model_dump(mode="json")

    assert payload["result"]["daily_ledger_decomposition"]["status"] == "unavailable"
    assert payload["findings"]["unexplained_amount"] == "0"
    assert payload["evidence_sufficiency"]["largest_verified_contribution"] == (
        "confirmed_settlement_income"
    )
    assert payload["evidence_sufficiency"]["allows_mainly_from"] is True
    assert any("两个比较期间长度不同" in warning for warning in payload["warnings"])
    assert "主要来自已确认公司结算收入变化" in payload["summary"]
