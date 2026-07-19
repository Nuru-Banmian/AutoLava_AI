import asyncio
from datetime import date, datetime
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import app.api.routes.ledger as ledger_routes
import app.services.ledger as ledger_service_module
from app.api.routes.ledger import _refresh_briefing_after_commit
from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.operations import DailyBriefing
from app.services.briefing import BriefingService
from app.services.ledger import LedgerService
from app.services.weather import FrozenWeatherLocation, WeatherResult


class StubWeatherService:
    def __init__(self, results: dict[date, WeatherResult | None] | None = None):
        self.results = results or {}

    async def get_daily(self, store: Store, target: date) -> WeatherResult | None:
        return self.results.get(target)


@pytest.fixture
async def store(store_factory) -> Store:
    return await store_factory(name="Briefing", timezone="Europe/Berlin")


async def test_yesterday_card_uses_integer_revenue_content_and_payload(
    db_session: AsyncSession, store: Store, user_factory
) -> None:
    owner = await user_factory(username="briefing-owner", password="secret")
    db_session.add(
        StoreDailyRecord(
            store_id=store.id,
            date=date(2026, 7, 14),
            daily_revenue=150,
            wash_count=12,
            is_open="营业",
            weather="晴",
            weather_edited=False,
            created_by=owner.id,
            updated_by=owner.id,
        )
    )
    await db_session.flush()

    cards = await BriefingService(db_session, StubWeatherService()).regenerate(
        store.id, ["yesterday"], local_date=date(2026, 7, 15)
    )

    assert cards[0].content == "昨天营业，营业额 €150。"
    assert cards[0].payload["revenue"] == 150
    assert isinstance(cards[0].payload["revenue"], int)


@pytest.mark.parametrize(
    ("record_status", "expected_state"),
    [
        (None, "missing"),
        ("营业", "recorded"),
        ("休息", "rest"),
        ("天气停业", "weather_closed"),
    ],
)
async def test_yesterday_states_are_deterministic(
    record_status,
    expected_state,
    db_session: AsyncSession,
    store: Store,
    user_factory,
) -> None:
    if record_status is not None:
        owner = await user_factory(username=f"state-{expected_state}", password="secret")
        db_session.add(
            StoreDailyRecord(
                store_id=store.id,
                date=date(2026, 7, 14),
                daily_revenue=150,
                is_open=record_status,
                weather_edited=False,
                created_by=owner.id,
                updated_by=owner.id,
            )
        )
        await db_session.flush()
    card = await BriefingService(db_session, StubWeatherService()).build_yesterday(
        store_id=store.id, local_date=date(2026, 7, 15)
    )
    assert card.state == expected_state
    assert card.revenue == (150 if record_status == "营业" else None)
    assert isinstance(card.generated_at, datetime)


async def test_sqlite_conflict_update_reuses_one_card(
    db_session: AsyncSession, store: Store
) -> None:
    service = BriefingService(db_session, StubWeatherService())
    first = await service.regenerate(
        store.id, ["today"], local_date=date(2026, 7, 13)
    )
    second = await service.regenerate(
        store.id,
        ["today"],
        local_date=date(2026, 7, 13),
        weather_overrides={date(2026, 7, 13): "晴"},
    )
    assert second[0].id == first[0].id
    assert second[0].content == "今天：晴；还未记账。"
    assert (
        await db_session.scalar(
            select(func.count())
            .select_from(DailyBriefing)
            .where(DailyBriefing.store_id == store.id)
        )
        == 1
    )


async def test_tomorrow_weather_values_remain_decimal_capable(
    db_session: AsyncSession, store: Store
) -> None:
    local_date = date(2026, 7, 13)
    service = BriefingService(
        db_session,
        StubWeatherService(
            {date(2026, 7, 14): WeatherResult("雨", 61, 22.5, 16.25, 4.2)}
        ),
    )
    card = await service.build_tomorrow(store=store, local_date=local_date)
    assert card.temperature_max == Decimal("22.5")
    assert card.temperature_min == Decimal("16.25")
    assert card.precipitation == Decimal("4.2")


async def test_regenerate_does_not_commit_callers_transaction(
    db_session: AsyncSession, store: Store
) -> None:
    await BriefingService(db_session, StubWeatherService()).regenerate(
        store.id, ["yesterday"], local_date=date(2026, 7, 13)
    )
    await db_session.rollback()
    assert (
        await db_session.scalar(select(func.count()).select_from(DailyBriefing))
        == 0
    )


async def test_ledger_write_blocks_briefing_write_section(
    db_session: AsyncSession,
    store: Store,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ledger_entered = asyncio.Event()
    release_ledger = asyncio.Event()
    briefing_entered = asyncio.Event()
    target = datetime.now(ZoneInfo(store.timezone)).date()

    async def hold_ledger(*_args, **_kwargs):
        ledger_entered.set()
        await release_ledger.wait()
        return True, 123, target

    async def canonical_record(*_args, **_kwargs):
        return SimpleNamespace(id=123, date=target)

    async def regenerate(*_args, **_kwargs):
        briefing_entered.set()
        return []

    async def no_transaction() -> None:
        return None

    async def fresh_access(*_args, **_kwargs):
        return SimpleNamespace(id=99), store

    monkeypatch.setattr(LedgerService, "_upsert_locked", hold_ledger)
    monkeypatch.setattr(LedgerService, "_find_record", canonical_record)
    monkeypatch.setattr(BriefingService, "regenerate", regenerate)
    monkeypatch.setattr(
        ledger_service_module, "require_fresh_store_access", fresh_access
    )
    monkeypatch.setattr(ledger_routes, "require_fresh_store_access", fresh_access)
    ledger_task = asyncio.create_task(
        LedgerService(
            SimpleNamespace(
                commit=no_transaction,
                rollback=no_transaction,
            )
        ).upsert(
            store_id=store.id,
            record_date=target,
            payload={},
            actor_id=99,
        )
    )
    await ledger_entered.wait()
    briefing_task = asyncio.create_task(
        _refresh_briefing_after_commit(
            SimpleNamespace(
                app=SimpleNamespace(
                    state=SimpleNamespace(weather_service=StubWeatherService())
                )
            ),
            db_session,
            actor_id=99,
            store_id=store.id,
            location=FrozenWeatherLocation.from_store(store),
            capability="ledger.edit",
            record_date=target,
        )
    )
    try:
        await asyncio.wait_for(briefing_entered.wait(), timeout=0.05)
        was_blocked = False
    except TimeoutError:
        was_blocked = True
    release_ledger.set()
    await asyncio.gather(ledger_task, briefing_task)
    assert was_blocked is True
    assert briefing_entered.is_set()
