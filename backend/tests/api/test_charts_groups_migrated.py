"""Public group comparisons on a disposable Alembic-migrated SQLite database."""

import os
import subprocess
import sys
from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session, sqlite_url
from app.core.security import hash_password
from app.main import create_app
from app.models.identity import Store, StoreMember, User
from app.models.ledger import StoreDailyRecord


class NoWeather:
    async def get_daily(self, store, target):
        return None


@pytest.fixture
async def group_analysis(tmp_path: Path) -> AsyncIterator[tuple]:
    database = tmp_path / "group-analysis.sqlite3"
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
                username="group-analysis-admin",
                password_hash=hash_password("AdminPass1"),
                role="admin",
            )
            store = Store(
                name="Group comparison fixture",
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
                json={"username": "group-analysis-admin", "password": "AdminPass1"},
            )
            assert login.status_code == 200, login.text
            yield client, store_id, factory
    finally:
        await engine.dispose()


async def save_day(
    client: AsyncClient,
    store_id: int,
    day: str,
    revenue: int | None,
    *,
    state: str = "营业",
    weather: str | None = "晴",
    config_revision: int = 1,
    items: list[dict] | None = None,
) -> None:
    saved = await client.put(
        f"/api/ledger/{store_id}/{day}",
        json={
            "expected_identity": None,
            "expected_revision": None,
            "expected_config_revision": config_revision,
            "is_open": state,
            "daily_revenue": revenue,
            "weather": weather,
            "weather_edited": True,
            "items": items or [],
        },
    )
    assert saved.status_code == 201, saved.text


async def get_groups(client: AsyncClient, store_id: int, query: str) -> dict:
    response = await client.get(f"/api/charts/{store_id}?{query}")
    assert response.status_code == 200, response.text
    return response.json()


async def test_group_amounts_include_early_rest_and_return_real_operating_sample_count(
    group_analysis,
) -> None:
    client, store_id, _ = group_analysis
    await save_day(client, store_id, "2026-07-06", 1)
    await save_day(client, store_id, "2026-07-13", 2, state="提前休息")

    payload = await get_groups(client, store_id, "start=2026-07-01&end=2026-07-31")

    # The two Mondays total €3: the independent worked example is €1.50 -> €2.
    assert payload["weather"] == [
        {"weather": "晴", "average_revenue": 2, "operating_day_count": 2},
    ]
    assert payload["weekday"] == [
        {"weekday": 0, "average_revenue": 2, "operating_day_count": 2},
    ]


async def test_weather_follows_the_fixed_contract_then_legacy_then_unrecorded(
    group_analysis,
) -> None:
    client, store_id, factory = group_analysis
    canonical = [
        "晴", "少云", "多云", "阴", "雾", "冻雾", "小毛毛雨", "毛毛雨", "大毛毛雨",
        "小冻毛毛雨", "冻毛毛雨", "小雨", "中雨", "大雨", "小冻雨", "冻雨", "小雪",
        "中雪", "大雪", "雪粒", "小阵雨", "阵雨", "大阵雨", "小阵雪", "大阵雪", "雷雨",
        "雷雨伴小冰雹", "雷雨伴大冰雹",
    ]
    for offset, weather in enumerate(reversed(canonical)):
        await save_day(
            client, store_id, (date(2026, 7, 1) + timedelta(days=offset)).isoformat(),
            offset + 1, weather=weather,
        )
    await save_day(client, store_id, "2026-07-29", 100)
    await save_day(client, store_id, "2026-07-30", 201)
    await save_day(client, store_id, "2026-07-31", 0, weather=None)
    # Seed historical values that the current public write contract correctly rejects.
    async with factory() as setup:
        for day, weather in ((date(2026, 7, 29), "旧版任意天气"), (date(2026, 7, 30), "天气暂时不可用")):
            await setup.execute(
                update(StoreDailyRecord)
                .where(StoreDailyRecord.store_id == store_id, StoreDailyRecord.date == day)
                .values(weather=weather)
            )
        await setup.commit()

    payload = await get_groups(client, store_id, "start=2026-07-01&end=2026-07-31")

    assert [row["weather"] for row in payload["weather"]] == [
        *canonical, "历史未规范天气", "未记录",
    ]
    assert [row["operating_day_count"] for row in payload["weather"]] == [*([1] * 28), 2, 1]
    assert payload["weather"][-2:] == [
        {"weather": "历史未规范天气", "average_revenue": 151, "operating_day_count": 2},
        {"weather": "未记录", "average_revenue": 0, "operating_day_count": 1},
    ]


async def test_groups_use_full_daily_ledger_and_keep_zero_rest_empty_and_scopes_distinct(
    group_analysis,
) -> None:
    client, store_id, _ = group_analysis
    configured = await client.put(
        f"/api/admin/stores/{store_id}/income-config",
        json={
            "expected_revision": 1, "enabled": True,
            "items": [
                {"name": "Cash", "include_in_total": True},
                {"name": "Card", "include_in_total": True},
                {"name": "Voucher", "include_in_total": False},
            ],
        },
    )
    assert configured.status_code == 200, configured.text
    category_ids = {item["name"]: item["id"] for item in configured.json()["items"]}
    for day, cash, card, voucher, state, weather in [
        ("2026-07-06", 1, 0, 900, "营业", "晴"),
        ("2026-07-13", 1, 1, 500, "提前休息", "晴"),
        ("2026-07-07", 0, 0, 40, "营业", None),
        ("2026-07-08", 1, 2, 10, "营业", "小雨"),
        ("2026-07-15", 1, 3, 10, "提前休息", "小雨"),
        ("2026-07-22", 1, 4, 10, "营业", "小雨"),
        ("2026-07-12", 0, 0, 0, "休息", "雷雨"),
        ("2026-07-31", 900, 0, 0, "营业", "晴"),
    ]:
        await save_day(
            client, store_id, day, None, state=state, weather=weather,
            config_revision=configured.json()["revision"],
            items=[
                {"category_id": category_ids["Cash"], "amount": cash},
                {"category_id": category_ids["Card"], "amount": card},
                {"category_id": category_ids["Voucher"], "amount": voucher},
            ],
        )

    company = await client.post(
        f"/api/settlements/{store_id}/companies", json={"name": "Group fixture company"}
    )
    assert company.status_code == 201, company.text
    record = await client.post(
        f"/api/settlements/{store_id}/records",
        json={"company_id": company.json()["id"], "opening_month": "2026-07", "amount": 300},
    )
    assert record.status_code == 201, record.text
    confirmed = await client.post(
        f"/api/settlements/{store_id}/records/{record.json()['id']}/confirm",
        json={"revision": record.json()["revision"]},
    )
    assert confirmed.status_code == 200, confirmed.text
    other = await client.post(
        "/api/admin/stores",
        json={"name": "Other group fixture", "address": "Test", "latitude": 45, "longitude": 9},
    )
    assert other.status_code == 201, other.text
    await save_day(client, other.json()["id"], "2026-07-06", 999, weather="雷雨")

    expected_weather = [
        {"weather": "晴", "average_revenue": 2, "operating_day_count": 2},
        {"weather": "小雨", "average_revenue": 4, "operating_day_count": 3},
        {"weather": "未记录", "average_revenue": 0, "operating_day_count": 1},
    ]
    expected_weekday = [
        {"weekday": 0, "average_revenue": 2, "operating_day_count": 2},
        {"weekday": 1, "average_revenue": 0, "operating_day_count": 1},
        {"weekday": 2, "average_revenue": 4, "operating_day_count": 3},
    ]
    query = "start=2026-07-01&end=2026-07-30"
    for suffix in ("", f"&category_id={category_ids['Cash']}", "&bucket=month"):
        payload = await get_groups(client, store_id, query + suffix)
        assert payload["weather"] == expected_weather
        assert payload["weekday"] == expected_weekday
        assert payload["income_summary"] == {
            "daily_ledger_revenue": 15, "confirmed_settlement_income": 300,
            "total_income": 315, "includes_settlement_income": True,
        }
    other_groups = await get_groups(client, other.json()["id"], query)
    assert other_groups["weather"] == [
        {"weather": "雷雨", "average_revenue": 999, "operating_day_count": 1},
    ]
    assert other_groups["weekday"] == [
        {"weekday": 0, "average_revenue": 999, "operating_day_count": 1},
    ]
    rainy = await get_groups(client, store_id, "start=2026-07-15&end=2026-07-22")
    assert rainy["weather"] == [
        {"weather": "小雨", "average_revenue": 5, "operating_day_count": 2},
    ]
    for start, end in (("2026-06-01", "2026-06-30"), ("2026-07-12", "2026-07-12")):
        empty = await get_groups(client, store_id, f"start={start}&end={end}")
        assert empty["weather"] == []
        assert empty["weekday"] == []


async def test_public_contract_requires_each_group_sample_count(group_analysis) -> None:
    client, _, _ = group_analysis
    response = await client.get("/openapi.json")
    assert response.status_code == 200, response.text
    schemas = response.json()["components"]["schemas"]
    for name in ("WeatherRevenue", "WeekdayRevenue"):
        assert "operating_day_count" in schemas[name]["required"]
        assert schemas[name]["properties"]["operating_day_count"]["type"] == "integer"
        assert schemas[name]["properties"]["operating_day_count"]["minimum"] == 0
