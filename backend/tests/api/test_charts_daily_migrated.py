"""Public daily analysis on a disposable Alembic-migrated SQLite database."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session, sqlite_url
from app.api.routes import charts as charts_route
from app.core.security import hash_password
from app.main import create_app
from app.models.identity import Store, StoreMember, User


class NoWeather:
    async def get_daily(self, store, target):
        return None


@pytest.fixture
async def analysis_client(tmp_path: Path) -> AsyncIterator[tuple[AsyncClient, int]]:
    database = tmp_path / "daily-analysis.sqlite3"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[2],
        env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(database)},
        check=True,
        capture_output=True,
    )
    engine = create_async_engine(sqlite_url(database))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as setup:
            user = User(
                username="daily-analysis-admin",
                password_hash=hash_password("AdminPass1"),
                role="admin",
            )
            store = Store(
                name="Daily analysis fixture",
                address="Test address",
                latitude=Decimal("45"),
                longitude=Decimal("9"),
                timezone="Europe/Rome",
                company_settlement_enabled=True,
                is_active=True,
            )
            setup.add_all([user, store])
            await setup.flush()
            setup.add(StoreMember(store_id=store.id, user_id=user.id))
            store_id = store.id
            await setup.commit()

        app = create_app()
        app.state.weather_service = NoWeather()

        async def override_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/api/auth/login",
                json={"username": "daily-analysis-admin", "password": "AdminPass1"},
            )
            assert login.status_code == 200, login.text
            yield client, store_id
    finally:
        await engine.dispose()


async def save_day(client: AsyncClient, store_id: int, day: str, revenue: int, state: str):
    saved = await client.put(
        f"/api/ledger/{store_id}/{day}",
        json={
            "expected_identity": None,
            "expected_revision": None,
            "expected_config_revision": 1,
            "is_open": state,
            "daily_revenue": revenue,
            "wash_count": None,
            "weather": None,
            "weather_edited": True,
            "items": [],
        },
    )
    assert saved.status_code == 201, saved.text


async def get_analysis(client: AsyncClient, store_id: int, query: str) -> dict:
    response = await client.get(f"/api/charts/{store_id}?{query}")
    assert response.status_code == 200, response.text
    return response.json()


async def confirm_settlement(client: AsyncClient, store_id: int, month: str, amount: int):
    company = await client.post(
        f"/api/settlements/{store_id}/companies", json={"name": f"Fixture {month}"}
    )
    assert company.status_code == 201, company.text
    record = await client.post(
        f"/api/settlements/{store_id}/records",
        json={"company_id": company.json()["id"], "opening_month": month, "amount": amount},
    )
    assert record.status_code == 201, record.text
    confirmed = await client.post(
        f"/api/settlements/{store_id}/records/{record.json()['id']}/confirm",
        json={"revision": record.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text


async def test_daily_analysis_distinguishes_recorded_zero_states_and_missing_days(
    analysis_client,
) -> None:
    client, store_id = analysis_client
    await save_day(client, store_id, "2026-07-10", 150, "营业")
    await save_day(client, store_id, "2026-07-11", 75, "提前休息")
    await save_day(client, store_id, "2026-07-12", 0, "休息")
    await save_day(client, store_id, "2026-07-14", 0, "营业")

    payload = await get_analysis(client, store_id, "start=2026-07-10&end=2026-07-15")

    assert payload["daily"] == [
        {"date": "2026-07-10", "revenue": 150, "is_open": "营业"},
        {"date": "2026-07-11", "revenue": 75, "is_open": "提前休息"},
        {"date": "2026-07-12", "revenue": 0, "is_open": "休息"},
        {"date": "2026-07-14", "revenue": 0, "is_open": "营业"},
    ]
    assert payload["period_coverage"] == {
        "start": "2026-07-10", "end": "2026-07-15", "record_days": 4, "interval_days": 6,
        "statistical_days": 4, "unreported_days": 0, "operating_days": 3, "rest_days": 1, "missing_record_days": 2,
    }


async def test_single_month_daily_comparison_uses_same_progress_and_excludes_settlement(
    analysis_client,
) -> None:
    client, store_id = analysis_client
    await save_day(client, store_id, "2026-07-10", 150, "营业")
    await save_day(client, store_id, "2026-07-11", 75, "提前休息")
    await save_day(client, store_id, "2026-06-10", 150, "提前休息")
    await save_day(client, store_id, "2026-06-12", 0, "休息")
    await save_day(client, store_id, "2026-06-15", 0, "营业")
    await save_day(client, store_id, "2026-06-09", 999, "营业")
    await save_day(client, store_id, "2026-06-16", 999, "营业")
    await confirm_settlement(client, store_id, "2026-07", 300)
    await confirm_settlement(client, store_id, "2026-06", 900)

    payload = await get_analysis(client, store_id, "start=2026-07-10&end=2026-07-15")

    assert payload["comparison_daily"] == [
        {"date": "2026-06-10", "revenue": 150, "is_open": "提前休息"},
        {"date": "2026-06-12", "revenue": 0, "is_open": "休息"},
        {"date": "2026-06-15", "revenue": 0, "is_open": "营业"},
    ]
    assert payload["comparison_coverage"] == {
        "start": "2026-06-10", "end": "2026-06-15", "record_days": 3, "interval_days": 6,
        "statistical_days": 3, "unreported_days": 0, "operating_days": 2, "rest_days": 1, "missing_record_days": 3,
    }
    assert payload["ledger_comparison"] == {
        "current_revenue": 225,
        "previous_revenue": 150,
        "change_percent": 50.0,
        "status": "comparable",
        "short_previous_month": False,
    }
    assert payload["income_summary"]["total_income"] == 525
    assert payload["comparison_kpis"] is None

    explicit = await get_analysis(
        client, store_id,
        "start=2026-07-10&end=2026-07-15&compare_start=2026-06-10&compare_end=2026-06-15",
    )
    assert explicit["comparison_kpis"]["total_revenue"] == 1050
    assert explicit["ledger_comparison"]["previous_revenue"] == 150
    assert explicit["ledger_comparison"]["change_percent"] == 50.0


async def test_current_month_ends_on_store_local_today_and_historical_month_stays_complete(
    analysis_client, monkeypatch,
) -> None:
    class FrozenClock:
        @staticmethod
        def now(timezone):
            return datetime(2026, 7, 14, 23, 30, tzinfo=UTC).astimezone(timezone)

    monkeypatch.setattr(charts_route, "datetime", FrozenClock)
    client, store_id = analysis_client
    for day, revenue in [
        ("2026-07-14", 150), ("2026-07-15", 75), ("2026-07-16", 999),
        ("2026-06-14", 100), ("2026-06-15", 50), ("2026-06-16", 999),
        ("2026-05-31", 45),
    ]:
        await save_day(client, store_id, day, revenue, "营业")

    rome = await get_analysis(client, store_id, "start=2026-07-01&end=2026-07-31")
    assert rome["range"] == {"start": "2026-07-01", "end": "2026-07-15", "bucket": "day"}
    assert rome["period_coverage"] == {
        "start": "2026-07-01", "end": "2026-07-15", "record_days": 2, "interval_days": 15,
        "statistical_days": 2, "unreported_days": 0, "operating_days": 2, "rest_days": 0, "missing_record_days": 13,
    }
    assert rome["comparison_coverage"] == {
        "start": "2026-06-01", "end": "2026-06-15", "record_days": 2, "interval_days": 15,
        "statistical_days": 2, "unreported_days": 0, "operating_days": 2, "rest_days": 0, "missing_record_days": 13,
    }
    assert rome["ledger_comparison"]["current_revenue"] == 225
    assert rome["ledger_comparison"]["previous_revenue"] == 150

    changed = await client.patch(
        f"/api/admin/stores/{store_id}", json={"timezone": "America/New_York"}
    )
    assert changed.status_code == 200, changed.text
    new_york = await get_analysis(client, store_id, "start=2026-07-01&end=2026-07-31")
    assert new_york["range"]["end"] == "2026-07-14"
    assert new_york["period_coverage"]["interval_days"] == 14
    assert new_york["ledger_comparison"]["current_revenue"] == 150
    assert new_york["ledger_comparison"]["previous_revenue"] == 100

    historical = await get_analysis(client, store_id, "start=2026-05-01&end=2026-05-31")
    assert historical["range"]["end"] == "2026-05-31"
    assert historical["period_coverage"]["interval_days"] == 31
    assert historical["daily"] == [
        {"date": "2026-05-31", "revenue": 45, "is_open": "营业"},
    ]


@pytest.mark.parametrize(
    ("start", "end", "prior_day", "expected_start", "expected_end", "interval", "short"),
    [
        ("2026-03-01", "2026-03-31", "2026-02-01", "2026-02-01", "2026-02-28", 28, True),
        ("2026-03-20", "2026-03-31", "2026-02-20", "2026-02-20", "2026-02-28", 9, True),
        ("2026-03-29", "2026-03-31", "2026-02-28", None, None, 0, True),
        ("2024-03-29", "2024-03-31", "2024-02-29", "2024-02-29", "2024-02-29", 1, True),
        ("2026-01-10", "2026-01-15", "2025-12-10", "2025-12-10", "2025-12-15", 6, False),
    ],
)
async def test_same_month_progress_respects_short_month_leap_day_and_year_boundary(
    analysis_client, start, end, prior_day, expected_start, expected_end, interval, short,
) -> None:
    client, store_id = analysis_client
    await save_day(client, store_id, start, 120, "营业")
    await save_day(client, store_id, prior_day, 60, "提前休息")

    payload = await get_analysis(client, store_id, f"start={start}&end={end}")

    assert payload["ledger_comparison"]["short_previous_month"] is short
    if expected_start is None:
        assert payload["comparison_coverage"] is None
        assert payload["comparison_daily"] == []
        assert payload["ledger_comparison"] == {
            "current_revenue": 120, "previous_revenue": None, "change_percent": None,
            "status": "no_comparison", "short_previous_month": True,
        }
    else:
        assert payload["comparison_coverage"] == {
            "start": expected_start, "end": expected_end, "record_days": 1,
            "interval_days": interval,
            "statistical_days": 1, "unreported_days": 0, "operating_days": 1, "rest_days": 0, "missing_record_days": interval - 1,
        }
        assert payload["comparison_daily"] == [
            {"date": prior_day, "revenue": 60, "is_open": "提前休息"},
        ]
        assert payload["ledger_comparison"]["previous_revenue"] == 60
        assert payload["ledger_comparison"]["change_percent"] == 100.0


@pytest.mark.parametrize(
    ("current_record", "previous_record", "status", "previous_revenue"),
    [
        (True, None, "no_previous_records", 0),
        (True, "休息", "zero_previous", 0),
        (True, "营业", "zero_previous", 0),
        (False, "提前休息", "no_current_records", 60),
    ],
)
async def test_daily_change_requires_observed_current_and_positive_previous_revenue(
    analysis_client, current_record, previous_record, status, previous_revenue,
) -> None:
    client, store_id = analysis_client
    if current_record:
        await save_day(client, store_id, "2026-07-10", 120, "营业")
    if previous_record is not None:
        await save_day(client, store_id, "2026-06-10", previous_revenue, previous_record)

    payload = await get_analysis(client, store_id, "start=2026-07-10&end=2026-07-10")

    assert payload["ledger_comparison"] == {
        "current_revenue": 120 if current_record else 0,
        "previous_revenue": previous_revenue,
        "change_percent": None,
        "status": status,
        "short_previous_month": False,
    }
    assert payload["comparison_coverage"]["record_days"] == (0 if previous_record is None else 1)
    assert payload["comparison_coverage"]["interval_days"] == 1


async def test_cross_month_keeps_explicit_comparison_and_monthly_settlement_grain(
    analysis_client,
) -> None:
    client, store_id = analysis_client
    for day, revenue in [
        ("2026-07-10", 100), ("2026-08-15", 50),
        ("2026-05-10", 25), ("2026-06-15", 25),
    ]:
        await save_day(client, store_id, day, revenue, "营业")
    for month, amount in [
        ("2026-07", 300), ("2026-08", 200), ("2026-05", 700), ("2026-06", 900),
    ]:
        await confirm_settlement(client, store_id, month, amount)

    query = "start=2026-07-10&end=2026-08-15&bucket=month"
    without_comparison = await get_analysis(client, store_id, query)
    assert without_comparison["comparison_coverage"] is None
    assert without_comparison["comparison_daily"] == []
    assert without_comparison["ledger_comparison"]["status"] == "no_comparison"
    assert without_comparison["range"] == {
        "start": "2026-07-10", "end": "2026-08-15", "bucket": "month",
    }

    payload = await get_analysis(
        client, store_id, query + "&compare_start=2026-05-10&compare_end=2026-06-15",
    )
    assert payload["period_coverage"] == {
        "start": "2026-07-10", "end": "2026-08-15", "record_days": 2, "interval_days": 37,
        "statistical_days": 2, "unreported_days": 0, "operating_days": 2, "rest_days": 0, "missing_record_days": 35,
    }
    assert payload["comparison_coverage"] == {
        "start": "2026-05-10", "end": "2026-06-15", "record_days": 2, "interval_days": 37,
        "statistical_days": 2, "unreported_days": 0, "operating_days": 2, "rest_days": 0, "missing_record_days": 35,
    }
    assert payload["ledger_comparison"] == {
        "current_revenue": 150, "previous_revenue": 50, "change_percent": 200.0,
        "status": "comparable", "short_previous_month": False,
    }
    assert payload["comparison_daily"] == [
        {"date": "2026-05-10", "revenue": 25, "is_open": "营业"},
        {"date": "2026-06-15", "revenue": 25, "is_open": "营业"},
    ]
    assert payload["comparison_kpis"]["total_revenue"] == 1650
    assert payload["income_summary"]["total_income"] == 650
    assert payload["monthly"] == [
        {
            "month": "2026-07", "revenue": 100, "daily_ledger_revenue": 100,
            "confirmed_settlement_income": 300, "monthly_total_income": 400,
        },
        {
            "month": "2026-08", "revenue": 50, "daily_ledger_revenue": 50,
            "confirmed_settlement_income": 200, "monthly_total_income": 250,
        },
    ]


async def test_current_month_future_only_subrange_is_rejected_as_no_effective_period(
    analysis_client, monkeypatch,
) -> None:
    class FrozenClock:
        @staticmethod
        def now(timezone):
            return datetime(2026, 7, 14, 23, 30, tzinfo=UTC).astimezone(timezone)

    monkeypatch.setattr(charts_route, "datetime", FrozenClock)
    client, store_id = analysis_client
    response = await client.get(
        f"/api/charts/{store_id}?start=2026-07-16&end=2026-07-31"
    )

    assert response.status_code == 422
    assert "local date" in response.json()["detail"]
