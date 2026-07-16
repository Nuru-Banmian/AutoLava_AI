import asyncio
from datetime import date, datetime
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory, engine
from app.models.base import Base
from app.models.identity import Store, User
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import DailyBriefing
from app.services.briefing import BriefingService
from app.services.weather import WeatherResult


class StubWeatherService:
    def __init__(self, results: dict[date, WeatherResult | None] | None = None):
        self.results = results or {}

    async def get_daily(self, store: Store, target: date) -> WeatherResult | None:
        return self.results.get(target)


@pytest.fixture
async def store(store_factory) -> Store:
    return await store_factory(name="Briefing", timezone="Europe/Berlin")


@pytest.fixture
def briefing_service(db_session: AsyncSession) -> BriefingService:
    return BriefingService(db_session, StubWeatherService())


async def test_yesterday_card_mentions_missing_record(briefing_service, store) -> None:
    cards = await briefing_service.regenerate(store.id, ["yesterday"], local_date=date(2026, 7, 13))
    assert cards[0].content == "昨天还没有经营记录，可以在记账页补录。"


@pytest.mark.parametrize(
    ("record_status", "expected_state"),
    [
        (None, "missing"),
        ("营业", "recorded"),
        ("休息", "rest"),
        ("天气停业", "weather_closed"),
    ],
)
async def test_yesterday_is_deterministic(
    record_status,
    expected_state,
    db_session: AsyncSession,
    store: Store,
    user_factory,
) -> None:
    if record_status is not None:
        owner = await user_factory(username=f"yesterday-{expected_state}", password="secret")
        db_session.add(
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 14),
                daily_revenue=Decimal("150.00"),
                wash_count=12,
                is_open=record_status,
                weather="晴",
                weather_auto="晴",
                weather_code=0,
                temperature_max=Decimal("30.00"),
                temperature_min=Decimal("20.00"),
                precipitation=Decimal("0.00"),
                activity="会员日",
                weather_edited=False,
                scanned=False,
                created_by=owner.id,
                updated_by=owner.id,
            )
        )
        await db_session.flush()

    card = await BriefingService(db_session, StubWeatherService()).build_yesterday(
        store_id=store.id, local_date=date(2026, 7, 15)
    )

    assert card.card_type == "yesterday"
    assert card.state == expected_state
    assert card.revenue == (Decimal("150.00") if record_status == "营业" else None)
    assert card.weather is None
    assert card.weekday is None
    assert card.temperature_max is None
    assert card.temperature_min is None
    assert card.precipitation is None
    assert card.hint is None
    assert isinstance(card.generated_at, datetime)


async def test_yesterday_card_excludes_categories_weather_washes_and_activity(
    db_session: AsyncSession, store: Store, user_factory
) -> None:
    owner: User = await user_factory(username="briefing-owner", password="secret")
    categories = [
        IncomeCategory(
            store_id=store.id,
            name=name,
            include_in_total=included,
            is_active=True,
            sort_order=order,
        )
        for name, included, order in [("洗车", True, 1), ("咖啡", True, 2), ("代收", False, 0)]
    ]
    db_session.add_all(categories)
    await db_session.flush()
    record = StoreDailyRecord(
        store_id=store.id,
        date=date(2026, 7, 12),
        daily_revenue=Decimal("150.00"),
        wash_count=12,
        is_open="营业",
        weather="晴",
        weather_auto="晴",
        weather_code=0,
        temperature_max=Decimal("30.00"),
        temperature_min=Decimal("20.00"),
        precipitation=Decimal("0.00"),
        activity="会员日",
        weather_edited=False,
        scanned=False,
        created_by=owner.id,
        updated_by=owner.id,
    )
    db_session.add(record)
    await db_session.flush()
    db_session.add_all(
        [
            DailyIncomeItem(record_id=record.id, category_id=categories[0].id, amount=100),
            DailyIncomeItem(record_id=record.id, category_id=categories[1].id, amount=50),
            DailyIncomeItem(record_id=record.id, category_id=categories[2].id, amount=999),
        ]
    )
    await db_session.flush()

    cards = await BriefingService(db_session, StubWeatherService()).regenerate(
        store.id, ["yesterday"], local_date=date(2026, 7, 13)
    )

    assert cards[0].content == "昨天营业，营业额 €150.00。"


async def test_today_and_tomorrow_copy_and_upsert(db_session: AsyncSession, store: Store) -> None:
    local_date = date(2026, 7, 13)
    sunny = WeatherResult("晴", 0, 30.0, 20.0, 0.0)
    service = BriefingService(
        db_session,
        StubWeatherService({local_date: None, date(2026, 7, 14): sunny}),
    )

    first = await service.regenerate(store.id, ["today", "tomorrow"], local_date=local_date)
    second = await service.regenerate(store.id, ["today"], local_date=local_date)

    assert "天气暂时不可用" in first[0].content
    assert "还未记账" in first[0].content
    assert first[1].content == "明天（星期二）：晴。"
    assert second[0].id == first[0].id
    rows = list(
        await db_session.scalars(select(DailyBriefing).where(DailyBriefing.store_id == store.id))
    )
    assert len(rows) == 2


async def test_today_and_tomorrow_persist_approved_structured_payloads(
    db_session: AsyncSession, store: Store, user_factory
) -> None:
    local_date = date(2026, 7, 15)
    owner = await user_factory(username="structured-cards", password="secret")
    db_session.add(
        StoreDailyRecord(
            store_id=store.id,
            date=local_date,
            daily_revenue=Decimal("321.00"),
            wash_count=8,
            is_open="营业",
            weather="手工天气",
            weather_auto="晴",
            weather_code=0,
            temperature_max=Decimal("30.00"),
            temperature_min=Decimal("20.00"),
            precipitation=Decimal("0.00"),
            activity="促销",
            weather_edited=True,
            scanned=False,
            created_by=owner.id,
            updated_by=owner.id,
        )
    )
    await db_session.flush()
    today_weather = WeatherResult("多云", 2, 27.5, 18.1, 0.2)
    tomorrow_weather = WeatherResult("雨", 61, 22.5, 16.0, 4.2)

    cards = await BriefingService(
        db_session,
        StubWeatherService(
            {local_date: today_weather, local_date.replace(day=16): tomorrow_weather}
        ),
    ).regenerate(store.id, ["today", "tomorrow"], local_date=local_date)

    assert cards[0].payload == {
        "card_type": "today",
        "state": "recorded",
        "revenue": "321.00",
        "weather": "多云",
        "weekday": None,
        "temperature_max": None,
        "temperature_min": None,
        "precipitation": None,
        "hint": None,
        "generated_at": cards[0].payload["generated_at"],
        "timestamp_status": "utc",
    }
    assert cards[1].payload == {
        "card_type": "tomorrow",
        "state": "forecast",
        "revenue": None,
        "weather": "雨",
        "weekday": "星期四",
        "temperature_max": "22.5",
        "temperature_min": "16.0",
        "precipitation": "4.2",
        "hint": None,
        "generated_at": cards[1].payload["generated_at"],
        "timestamp_status": "utc",
    }
    assert [card.timestamp_contract for card in cards] == ["utc_v1", "utc_v1"]


async def _committed_store() -> int:
    if engine.dialect.name != "mysql" or engine.url.database != "autolava_test":
        pytest.fail("Concurrency test requires the dedicated autolava_test database")
    async with engine.begin() as connection:
        for table in reversed(Base.metadata.sorted_tables):
            await connection.execute(table.delete())
    async with async_session_factory() as setup:
        store = Store(
            name="Concurrent briefing",
            address="Test",
            latitude=Decimal("45.000000"),
            longitude=Decimal("9.000000"),
            timezone="Europe/Berlin",
            is_active=True,
        )
        setup.add(store)
        await setup.commit()
        return store.id


async def test_regenerate_does_not_commit_callers_transaction() -> None:
    store_id = await _committed_store()
    async with async_session_factory() as session:
        await BriefingService(session, StubWeatherService()).regenerate(
            store_id, ["yesterday"], local_date=date(2026, 7, 13)
        )
        await session.rollback()

    async with async_session_factory() as verify:
        count = await verify.scalar(
            select(func.count())
            .select_from(DailyBriefing)
            .where(DailyBriefing.store_id == store_id)
        )
        assert count == 0


@pytest.mark.parametrize("repeat", range(3))
async def test_concurrent_first_regenerate_atomically_upserts_one_card(repeat: int) -> None:
    store_id = await _committed_store()
    barrier = asyncio.Barrier(2)

    class BarrierWeather:
        async def get_daily(self, store, target):
            await barrier.wait()
            return WeatherResult("晴", 0, 30.0, 20.0, 0.0)

    async def regenerate_and_commit() -> list[DailyBriefing]:
        async with async_session_factory() as session:
            cards = await BriefingService(session, BarrierWeather()).regenerate(
                store_id, ["today"], local_date=date(2026, 7, 13)
            )
            await session.commit()
            return cards

    results = await asyncio.gather(regenerate_and_commit(), regenerate_and_commit())
    assert [len(cards) for cards in results] == [1, 1], repeat
    assert results[0][0].id == results[1][0].id

    async with async_session_factory() as verify:
        cards = list(
            await verify.scalars(
                select(DailyBriefing).where(
                    DailyBriefing.store_id == store_id,
                    DailyBriefing.card_type == "today",
                )
            )
        )
        assert len(cards) == 1
