from datetime import date
from decimal import Decimal

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
        daily_revenue=Decimal("125.00"),
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
        DailyIncomeItem(record_id=record.id, category_id=category.id, amount=Decimal("25.00"))
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
        {"category_id": included.id, "category_name": "Included", "amount": "25.00"}
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
    assert payload["kpis"]["total_revenue"] == "125.00"
    assert payload["daily"] == [{"date": "2026-07-12", "revenue": "125.00"}]
    assert payload["categories"] == [
        {"category_id": category.id, "category_name": "Optional", "amount": "25.00"}
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
            "total_revenue": "0.00",
            "record_days": 0,
            "open_days": 0,
            "average_revenue": "0.00",
            "primary_categories": [],
            "total_wash_count": None,
            "average_ticket": None,
        },
        "daily": [],
        "categories": [],
        "monthly": [],
        "weather": [],
        "weekday": [],
    }
