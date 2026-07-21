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
        daily_revenue=150,
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
        daily_revenue=200,
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
            DailyIncomeItem(
                record_id=first.id,
                category_id=cash.id,
                category_name=cash.name,
                include_in_total=cash.include_in_total,
                sort_order=cash.sort_order,
                amount=100,
            ),
            DailyIncomeItem(
                record_id=first.id,
                category_id=card.id,
                category_name=card.name,
                include_in_total=card.include_in_total,
                sort_order=card.sort_order,
                amount=50,
            ),
            DailyIncomeItem(
                record_id=second.id,
                category_id=cash.id,
                category_name=cash.name,
                include_in_total=cash.include_in_total,
                sort_order=cash.sort_order,
                amount=200,
            ),
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

    assert result["kpis"]["total_revenue"] == 350
    assert result["kpis"]["record_days"] == 2
    assert result["kpis"]["open_days"] == 1
    assert result["kpis"]["average_revenue"] == 350
    assert result["kpis"]["total_wash_count"] == 5
    assert result["kpis"]["average_ticket"] == 70
    assert result["daily"][0] == {"date": "2026-07-12", "revenue": 150}
    assert result["monthly"] == [
        {
            "month": "2026-07",
            "revenue": 350,
            "daily_ledger_revenue": 350,
            "confirmed_settlement_income": 0,
            "monthly_total_income": 350,
        }
    ]
    assert {item["weather"] for item in result["weather"]} == {"晴", "未记录"}
    assert [item["weekday"] for item in result["weekday"]] == [0, 6]


async def test_total_only_records_affect_trend_not_composition(
    db_session: AsyncSession,
) -> None:
    store, category_ids = await _seed_records(db_session, suffix="-legacy")
    records = list(
        await db_session.scalars(
            select(StoreDailyRecord)
            .where(StoreDailyRecord.store_id == store.id)
            .order_by(StoreDailyRecord.date)
        )
    )
    for record in records:
        record.items.clear()
    records[0].daily_revenue = 100
    records[1].daily_revenue = 0
    await db_session.flush()

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=category_ids,
    )

    assert result["kpis"]["total_revenue"] == 100
    assert result["daily"][0]["revenue"] == 100
    assert result["categories"] == []
    assert result["classified_included_total"] == 0
    assert result["excluded_categories"] == []
    assert result["kpis"]["average_revenue"] == 100


async def test_snapshot_composition_preserves_groups_order_and_archived_names(
    db_session: AsyncSession,
) -> None:
    store, category_ids = await _seed_records(db_session, suffix="-composition")
    cash_id, card_id = category_ids
    records = list(
        await db_session.scalars(
            select(StoreDailyRecord)
            .where(StoreDailyRecord.store_id == store.id)
            .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
        )
    )
    archived = IncomeCategory(
        store_id=store.id,
        name="当前归档名称",
        include_in_total=False,
        is_active=False,
        sort_order=9,
    )
    db_session.add(archived)
    await db_session.flush()
    db_session.add(
        DailyIncomeItem(
            record_id=records[0].id,
            category_id=archived.id,
            category_name="历史优惠券",
            include_in_total=False,
            sort_order=0,
            amount=7,
        )
    )
    june = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 6, 10),
        daily_revenue=80,
        wash_count=None,
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
        created_by=records[0].created_by,
        updated_by=records[0].updated_by,
    )
    db_session.add(june)
    await db_session.flush()

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=None,
        compare_start=date(2026, 6, 1),
        compare_end=date(2026, 6, 30),
        bucket="day",
    )

    assert [row["category_id"] for row in result["categories"]] == [cash_id, card_id]
    assert result["classified_included_total"] == 350
    assert result["kpis"]["total_revenue"] == 350
    assert result["excluded_categories"] == [
        {
            "category_id": archived.id,
            "category_name": "历史优惠券",
            "amount": 7,
        }
    ]
    assert result["comparison_kpis"] == {
        "start": "2026-06-01",
        "end": "2026-06-30",
        "total_revenue": 80,
        "open_days": 1,
        "average_revenue": 80,
    }


async def test_average_revenue_is_zero_without_open_days(db_session: AsyncSession) -> None:
    store, category_ids = await _seed_records(db_session, suffix="-closed")
    records = await db_session.scalars(
        select(StoreDailyRecord).where(StoreDailyRecord.store_id == store.id)
    )
    for record in records:
        record.is_open = "休息"
    await db_session.flush()

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=category_ids,
    )

    assert result["kpis"]["average_revenue"] == 0


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

    assert result["kpis"]["total_revenue"] == 350
    assert result["kpis"]["record_days"] == 2
    assert [item["amount"] for item in result["categories"]] == [300, 50]


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
    items[0].amount = 25
    items[1].amount = 50
    items[2].amount = 25
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
    assert all(isinstance(item["average_revenue"], int) for item in result["weather"])
    assert all(isinstance(item["average_revenue"], int) for item in result["weekday"])


async def test_fractional_averages_use_round_half_up(db_session: AsyncSession) -> None:
    store, category_ids = await _seed_records(db_session, suffix="-rounding")
    records = list(
        await db_session.scalars(
            select(StoreDailyRecord)
            .where(StoreDailyRecord.store_id == store.id)
            .order_by(StoreDailyRecord.date)
        )
    )
    records[0].daily_revenue = 1
    records[1].daily_revenue = 2
    records[1].is_open = "营业"
    await db_session.flush()

    result = await AnalyticsService(db_session).calculate(
        store_id=store.id,
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
        category_ids=category_ids,
    )

    assert result["kpis"]["average_revenue"] == 2
