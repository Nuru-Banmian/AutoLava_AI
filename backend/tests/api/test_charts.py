from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, StoreMember, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord


async def _assigned_store(auth_client, db_session: AsyncSession, store_factory) -> Store:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    store = await store_factory(name="Charts", timezone="Europe/Berlin")
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.flush()
    return store


async def _record(db_session: AsyncSession, store: Store, category: IncomeCategory) -> None:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 12),
        daily_revenue=125,
        wash_count=None,
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
        "classified_included_total": 0,
        "daily": [],
        "categories": [],
        "excluded_categories": [],
        "monthly": [],
        "weather": [],
        "weekday": [],
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
