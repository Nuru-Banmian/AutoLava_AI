from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

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


async def test_yesterday_card_is_deterministic_and_only_uses_included_categories(
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

    content = cards[0].content
    assert "营业额 €150.00" in content
    assert "洗车 €100.00、咖啡 €50.00" in content
    assert "代收" not in content
    assert "营业" in content
    assert "晴" in content
    assert "洗车 12 辆" in content
    assert "会员日" in content


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
