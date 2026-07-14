from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.services.analytics import AnalyticsService


async def _seed_records(
    session: AsyncSession, *, with_wash: bool = True, suffix: str = ""
) -> tuple[Store, list[int]]:
    user = User(
        username=f"analytics-owner{suffix}",
        password_hash="unused",
        role="admin",
        is_active=True,
        remember_token=None,
    )
    store = Store(
        name=f"Analytics{suffix}",
        address="Analytics address",
        latitude=Decimal("45.000000"),
        longitude=Decimal("9.000000"),
        timezone="Europe/Berlin",
        is_active=True,
    )
    session.add_all([user, store])
    await session.flush()
    cash = IncomeCategory(store_id=store.id, name="现金", include_in_total=True, sort_order=1)
    card = IncomeCategory(store_id=store.id, name="刷卡", include_in_total=True, sort_order=2)
    session.add_all([cash, card])
    await session.flush()
    first = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 12),
        daily_revenue=Decimal("150.00"),
        wash_count=3 if with_wash else None,
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
    second = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 13),
        daily_revenue=Decimal("200.00"),
        wash_count=2 if with_wash else None,
        is_open="休息",
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
    )
    session.add_all([first, second])
    await session.flush()
    session.add_all(
        [
            DailyIncomeItem(record_id=first.id, category_id=cash.id, amount=Decimal("100.00")),
            DailyIncomeItem(record_id=first.id, category_id=card.id, amount=Decimal("50.00")),
            DailyIncomeItem(record_id=second.id, category_id=cash.id, amount=Decimal("200.00")),
        ]
    )
    await session.flush()
    return store, [cash.id, card.id]


async def test_analytics_returns_expected_groups(db_session: AsyncSession) -> None:
    store, category_ids = await _seed_records(db_session)

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=category_ids,
    )

    assert result["kpis"]["total_revenue"] == "350.00"
    assert result["kpis"]["record_days"] == 2
    assert result["kpis"]["open_days"] == 1
    assert result["kpis"]["total_wash_count"] == 5
    assert result["kpis"]["average_ticket"] == "70.00"
    assert result["daily"][0] == {"date": "2026-07-12", "revenue": "150.00"}
    assert result["monthly"] == [{"month": "2026-07", "revenue": "350.00"}]
    assert {item["weather"] for item in result["weather"]} == {"晴", "未记录"}
    assert [item["weekday"] for item in result["weekday"]] == [0, 6]


async def test_wash_metrics_are_null_without_recorded_counts(db_session: AsyncSession) -> None:
    store, category_ids = await _seed_records(db_session, with_wash=False)

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=category_ids,
    )

    assert result["kpis"]["total_wash_count"] is None
    assert result["kpis"]["average_ticket"] is None


async def test_zero_wash_count_has_no_average_ticket(db_session: AsyncSession) -> None:
    store, category_ids = await _seed_records(db_session)
    records = await db_session.scalars(
        select(StoreDailyRecord).where(StoreDailyRecord.store_id == store.id)
    )
    for record in records:
        record.wash_count = 0
    await db_session.flush()

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=category_ids,
    )

    assert result["kpis"]["total_wash_count"] == 0
    assert result["kpis"]["average_ticket"] is None


async def test_analytics_never_mixes_another_store(db_session: AsyncSession) -> None:
    store, category_ids = await _seed_records(db_session, suffix="-target")
    await _seed_records(db_session, suffix="-other")

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=category_ids,
    )

    assert result["kpis"]["total_revenue"] == "350.00"
    assert result["kpis"]["record_days"] == 2
    assert [item["amount"] for item in result["categories"]] == ["300.00", "50.00"]


async def test_equal_primary_categories_use_category_id_tie_break(
    db_session: AsyncSession,
) -> None:
    store, category_ids = await _seed_records(db_session)
    items = list(
        await db_session.scalars(
            select(DailyIncomeItem)
            .join(StoreDailyRecord)
            .where(StoreDailyRecord.store_id == store.id)
            .order_by(DailyIncomeItem.id)
        )
    )
    items[0].amount = Decimal("25.00")
    items[1].amount = Decimal("50.00")
    items[2].amount = Decimal("25.00")
    await db_session.flush()

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=category_ids,
    )

    assert [item["category_id"] for item in result["kpis"]["primary_categories"]] == sorted(
        category_ids
    )
    assert all(isinstance(item["average_revenue"], str) for item in result["weather"])
    assert all(isinstance(item["average_revenue"], str) for item in result["weekday"])
