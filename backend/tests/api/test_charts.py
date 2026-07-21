from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord


async def _assigned_store(auth_client, db_session: AsyncSession, store_factory) -> Store:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    store = await store_factory(name="Charts", timezone="Europe/Berlin")
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.flush()
    return store


async def _record(
    db_session: AsyncSession,
    store: Store,
    category: IncomeCategory,
    *,
    record_date: date = date(2026, 7, 12),
    revenue: int = 125,
    wash_count: int | None = None,
) -> None:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    record = StoreDailyRecord(
        store_id=store.id,
        date=record_date,
        daily_revenue=revenue,
        wash_count=wash_count,
        is_open="营业",
        weather="晴",
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
    )
    db_session.add(record)
    await db_session.flush()
    db_session.add(
        DailyIncomeItem(
            record_id=record.id,
            category_id=category.id,
            category_name=category.name,
            include_in_total=category.include_in_total,
            sort_order=category.sort_order,
            amount=25,
        )
    )
    await db_session.flush()


async def _confirmed_settlement(
    db_session: AsyncSession,
    store: Store,
    *,
    opening_month: date,
    amount: int,
) -> None:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    company = SettlementCompany(
        store_id=store.id,
        name=f"Company {opening_month.isoformat()}",
        normalized_name=f"company {opening_month.isoformat()}",
        is_active=True,
        created_by=user.id,
        updated_by=user.id,
    )
    db_session.add(company)
    await db_session.flush()
    db_session.add(
        SettlementRecord(
            store_id=store.id,
            company_id=company.id,
            company_name=company.name,
            opening_month=opening_month,
            amount=amount,
            status="confirmed",
            revision=2,
            created_by=user.id,
            updated_by=user.id,
        )
    )
    await db_session.flush()


async def test_charts_requires_authentication(client) -> None:
    response = await client.get("/api/charts/1?start=2026-07-01&end=2026-07-31")
    assert response.status_code == 401


async def test_charts_rejects_reversed_date_range(auth_client, db_session, store_factory) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    response = await auth_client.get(f"/api/charts/{store.id}?start=2026-07-31&end=2026-07-01")
    assert response.status_code == 422


async def test_charts_hides_unassigned_store(auth_client, store_factory) -> None:
    store = await store_factory(name="Hidden")
    response = await auth_client.get(f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31")
    assert response.status_code == 404


async def test_charts_defaults_to_included_categories(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    included = IncomeCategory(
        store_id=store.id, name="Included", include_in_total=True, sort_order=1
    )
    excluded = IncomeCategory(
        store_id=store.id, name="Excluded", include_in_total=False, sort_order=2
    )
    db_session.add_all([included, excluded])
    await db_session.flush()
    await _record(db_session, store, included)

    response = await auth_client.get(f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31")

    assert response.status_code == 200
    assert response.json()["categories"] == [
        {"category_id": included.id, "category_name": "Included", "amount": 25}
    ]


async def test_charts_deduplicates_explicit_categories_without_changing_kpis(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    category = IncomeCategory(
        store_id=store.id, name="Optional", include_in_total=False, sort_order=1
    )
    db_session.add(category)
    await db_session.flush()
    await _record(db_session, store, category)

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31"
        f"&category_id={category.id}&category_id={category.id}"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["kpis"]["total_revenue"] == 125
    assert payload["daily"] == [{"date": "2026-07-12", "revenue": 125}]
    assert payload["categories"] == [
        {"category_id": category.id, "category_name": "Optional", "amount": 25}
    ]


async def test_charts_rejects_category_from_another_store(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    other = await store_factory(name="Other")
    category = IncomeCategory(store_id=other.id, name="Foreign", include_in_total=True)
    db_session.add(category)
    await db_session.flush()

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31&category_id={category.id}"
    )
    assert response.status_code == 422


async def test_charts_returns_stable_empty_result(auth_client, db_session, store_factory) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    response = await auth_client.get(f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31")

    assert response.status_code == 200
    assert response.json() == {
        "kpis": {
            "total_revenue": 0,
            "record_days": 0,
            "open_days": 0,
            "average_revenue": 0,
            "primary_categories": [],
            "total_wash_count": None,
            "average_ticket": None,
        },
        "range": {"start": "2026-07-01", "end": "2026-07-31", "bucket": "day"},
        "comparison_kpis": None,
        "income_summary": {
            "daily_ledger_revenue": 0,
            "confirmed_settlement_income": 0,
            "total_income": 0,
            "includes_settlement_income": False,
        },
        "classified_included_total": 0,
        "daily": [],
        "categories": [],
        "excluded_categories": [],
        "monthly": [],
        "weather": [],
        "weekday": [],
    }


async def test_charts_enabled_store_exposes_settlement_summary_for_partial_month(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    store.company_settlement_enabled = True
    await db_session.flush()

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-10&end=2026-07-20"
    )

    assert response.status_code == 200
    assert response.json()["income_summary"] == {
        "daily_ledger_revenue": 0,
        "confirmed_settlement_income": 0,
        "total_income": 0,
        "includes_settlement_income": True,
    }


async def test_charts_defaults_bucket_and_comparison_for_existing_callers(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31"
    )
    assert response.status_code == 200
    assert response.json()["range"] == {
        "start": "2026-07-01",
        "end": "2026-07-31",
        "bucket": "day",
    }
    assert response.json()["comparison_kpis"] is None


async def test_charts_requires_a_complete_valid_comparison_pair(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    base = f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31"
    missing_end = await auth_client.get(base + "&compare_start=2026-06-01")
    missing_start = await auth_client.get(base + "&compare_end=2026-06-30")
    reversed_range = await auth_client.get(
        base + "&compare_start=2026-06-30&compare_end=2026-06-01"
    )
    assert [missing_end.status_code, missing_start.status_code, reversed_range.status_code] == [
        422,
        422,
        422,
    ]


async def test_charts_accepts_month_bucket_and_returns_excluded_snapshot_items(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    excluded = IncomeCategory(
        store_id=store.id,
        name="当前名称",
        include_in_total=False,
        is_active=False,
        sort_order=3,
    )
    db_session.add(excluded)
    await db_session.flush()
    await _record(db_session, store, excluded)
    item = await db_session.scalar(
        select(DailyIncomeItem).where(DailyIncomeItem.category_id == excluded.id)
    )
    assert item is not None
    item.category_name = "历史优惠券"
    item.include_in_total = False
    item.sort_order = 1
    await db_session.flush()

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-07-01&end=2026-07-31&bucket=month"
    )

    assert response.status_code == 200
    assert response.json()["range"]["bucket"] == "month"
    assert response.json()["categories"] == []
    assert response.json()["excluded_categories"] == [
        {
            "category_id": excluded.id,
            "category_name": "历史优惠券",
            "amount": 25,
        }
    ]


async def test_charts_complete_calendar_month_includes_confirmed_settlement_history(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    category = IncomeCategory(
        store_id=store.id, name="Cash", include_in_total=True, sort_order=1
    )
    db_session.add(category)
    await db_session.flush()
    await _record(
        db_session,
        store,
        category,
        record_date=date(2026, 6, 12),
        revenue=125,
        wash_count=5,
    )
    await _confirmed_settlement(
        db_session, store, opening_month=date(2026, 6, 1), amount=300
    )
    await _confirmed_settlement(
        db_session, store, opening_month=date(2026, 5, 1), amount=100
    )
    assert store.company_settlement_enabled is False

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-06-01&end=2026-06-30&bucket=month"
        "&compare_start=2026-05-01&compare_end=2026-05-31"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["income_summary"] == {
        "daily_ledger_revenue": 125,
        "confirmed_settlement_income": 300,
        "total_income": 425,
        "includes_settlement_income": True,
    }
    assert payload["kpis"]["total_revenue"] == 425
    assert payload["kpis"]["average_revenue"] == 125
    assert payload["kpis"]["average_ticket"] == 25
    assert payload["categories"] == [
        {"category_id": category.id, "category_name": "Cash", "amount": 25},
        {"category_id": None, "category_name": "公司结算", "amount": 300},
    ]
    assert payload["classified_included_total"] == 325
    assert payload["comparison_kpis"]["total_revenue"] == 100
    assert payload["daily"] == [{"date": "2026-06-12", "revenue": 125}]
    assert payload["monthly"] == [
        {
            "month": "2026-06",
            "revenue": 125,
            "daily_ledger_revenue": 125,
            "confirmed_settlement_income": 300,
            "monthly_total_income": 425,
        }
    ]


async def test_charts_partial_month_includes_confirmed_settlement_for_overlapping_month(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    category = IncomeCategory(
        store_id=store.id, name="Cash", include_in_total=True, sort_order=1
    )
    db_session.add(category)
    await db_session.flush()
    await _record(
        db_session,
        store,
        category,
        record_date=date(2026, 6, 12),
        revenue=125,
    )
    await _confirmed_settlement(
        db_session, store, opening_month=date(2026, 6, 1), amount=300
    )

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-06-02&end=2026-06-30&bucket=month"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["income_summary"] == {
        "daily_ledger_revenue": 125,
        "confirmed_settlement_income": 300,
        "total_income": 425,
        "includes_settlement_income": True,
    }
    assert payload["kpis"]["total_revenue"] == 425
    assert payload["categories"][-1] == {
        "category_id": None,
        "category_name": "公司结算",
        "amount": 300,
    }
    assert payload["monthly"][0]["revenue"] == 125
    assert payload["monthly"][0]["confirmed_settlement_income"] == 300
    assert payload["monthly"][0]["monthly_total_income"] == 425


async def test_charts_complete_multi_month_range_sums_each_month_total(
    auth_client, db_session, store_factory
) -> None:
    store = await _assigned_store(auth_client, db_session, store_factory)
    category = IncomeCategory(
        store_id=store.id, name="Cash", include_in_total=True, sort_order=1
    )
    db_session.add(category)
    await db_session.flush()
    await _record(
        db_session, store, category, record_date=date(2026, 6, 12), revenue=125
    )
    await _confirmed_settlement(
        db_session, store, opening_month=date(2026, 6, 1), amount=300
    )
    await _confirmed_settlement(
        db_session, store, opening_month=date(2026, 7, 1), amount=200
    )

    response = await auth_client.get(
        f"/api/charts/{store.id}?start=2026-06-01&end=2026-07-31&bucket=month"
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["income_summary"]["total_income"] == 625
    assert payload["kpis"]["total_revenue"] == 625
    assert [row["monthly_total_income"] for row in payload["monthly"]] == [425, 200]
