from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

import httpx
from starlette.requests import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.routes.dashboard import RefreshLimiter
from app.api.routes.ledger import _refresh_briefing_after_commit
from app.models.identity import Store, StoreMember, User
from app.models.operations import DailyBriefing
from app.services.weather import FrozenWeatherLocation


async def _assign_store(auth_client, db_session: AsyncSession, store_factory) -> Store:
    user = await db_session.scalar(select(User).where(User.username == "authenticated"))
    assert user is not None
    store = await store_factory(name="Dashboard", timezone="Europe/Berlin")
    db_session.add(StoreMember(store_id=store.id, user_id=user.id))
    await db_session.flush()
    return store


async def test_dashboard_returns_cached_cards(auth_client, db_session, store_factory) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)
    db_session.add_all(
        [
            DailyBriefing(store_id=store.id, card_type="tomorrow", content="C"),
            DailyBriefing(store_id=store.id, card_type="yesterday", content="A"),
            DailyBriefing(store_id=store.id, card_type="today", content="B"),
        ]
    )
    await db_session.flush()

    response = await auth_client.get(f"/api/dashboard/{store.id}")

    assert response.status_code == 200
    assert [card["card_type"] for card in response.json()] == ["yesterday", "today", "tomorrow"]


async def test_dashboard_returns_cached_revenue_as_integer(
    auth_client, db_session, store_factory
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)
    db_session.add(
        DailyBriefing(
            store_id=store.id,
            card_type="today",
            content="integer",
            payload={
                "card_type": "today",
                "state": "recorded",
                "revenue": 321,
                "generated_at": "2026-07-15T04:00:00Z",
            },
            timestamp_contract="utc_v1",
        )
    )
    await db_session.flush()

    response = await auth_client.get(f"/api/dashboard/{store.id}")

    assert response.status_code == 200
    assert response.json()[0]["revenue"] == 321
    assert isinstance(response.json()[0]["revenue"], int)


async def test_dashboard_returns_structured_payload_without_calling_weather(
    auth_client, db_session, store_factory
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)
    generated_at = datetime(2026, 7, 15, 4, 0)
    db_session.add(
        DailyBriefing(
            store_id=store.id,
            card_type="today",
            content="兼容文本",
            payload={
                "card_type": "today",
                "state": "missing",
                "revenue": None,
                "weather": "多云",
                "weekday": None,
                "temperature_max": None,
                "temperature_min": None,
                "precipitation": None,
                "hint": None,
                "generated_at": generated_at.isoformat(),
            },
        )
    )
    await db_session.flush()
    weather = auth_client._transport.app.state.weather_service
    weather.get_daily = AsyncMock(side_effect=AssertionError("GET must be cache-only"))

    response = await auth_client.get(f"/api/dashboard/{store.id}")

    assert response.status_code == 200
    assert response.json() == [
        {
            "card_type": "today",
            "state": "missing",
            "revenue": None,
            "weather": "多云",
            "weekday": None,
            "temperature_max": None,
            "temperature_min": None,
            "precipitation": None,
            "hint": None,
            "generated_at": None,
            "timestamp_status": "legacy_unknown",
        }
    ]
    weather.get_daily.assert_not_awaited()


async def test_dashboard_normalizes_offset_timestamp_to_utc(
    auth_client, db_session, store_factory
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)
    db_session.add(
        DailyBriefing(
            store_id=store.id,
            card_type="today",
            content="offset",
            payload={
                "card_type": "today",
                "state": "missing",
                "generated_at": "2026-07-15T06:00:00+02:00",
            },
            timestamp_contract="utc_v1",
        )
    )
    await db_session.flush()

    response = await auth_client.get(f"/api/dashboard/{store.id}")

    assert response.status_code == 200
    assert response.json()[0]["generated_at"] == "2026-07-15T04:00:00Z"
    assert response.json()[0]["timestamp_status"] == "utc"


async def test_dashboard_old_cache_row_falls_back_to_unavailable(
    auth_client, db_session, store_factory
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)
    card = DailyBriefing(store_id=store.id, card_type="yesterday", content="旧缓存")
    db_session.add(card)
    await db_session.flush()

    response = await auth_client.get(f"/api/dashboard/{store.id}")

    body = response.json()[0]
    assert body["card_type"] == "yesterday"
    assert body["state"] == "unavailable"
    assert body["revenue"] is None
    assert body["hint"] is None


async def test_yesterday_ledger_change_regenerates_only_yesterday(
    auth_client, db_session, store_factory, monkeypatch
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)
    regenerate = AsyncMock(return_value=[])
    monkeypatch.setattr("app.services.briefing.BriefingService.regenerate", regenerate)
    local_date = datetime.now(ZoneInfo(store.timezone)).date()
    user = await db_session.scalar(
        select(User).where(User.username == "authenticated")
    )
    assert user is not None
    actor_id = user.id
    store_id = store.id
    location = FrozenWeatherLocation.from_store(store)
    await db_session.commit()

    await _refresh_briefing_after_commit(
        Request({"type": "http", "app": auth_client._transport.app}),
        db_session,
        actor_id=actor_id,
        store_id=store_id,
        location=location,
        capability="ledger.edit",
        record_date=local_date - timedelta(days=1),
    )

    assert regenerate.await_args.args[1] == ["yesterday"]


async def test_manual_refresh_is_limited_per_user_and_store(
    auth_client, db_session, store_factory
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)

    first = await auth_client.post(f"/api/dashboard/{store.id}/refresh")
    second = await auth_client.post(f"/api/dashboard/{store.id}/refresh")

    assert first.status_code == 200
    assert second.status_code == 429
    assert second.json()["detail"] == "请等待五分钟后再刷新"


def test_refresh_limiter_is_per_user_store_and_per_app_instance() -> None:
    now = [1000.0]
    first_app = RefreshLimiter(clock=lambda: now[0])

    assert first_app.allow(user_id=1, store_id=1) is True
    assert first_app.allow(user_id=1, store_id=1) is False
    assert first_app.allow(user_id=1, store_id=2) is True
    assert first_app.allow(user_id=2, store_id=1) is True

    second_app = RefreshLimiter(clock=lambda: now[0])
    assert second_app.allow(user_id=1, store_id=1) is True


async def test_weather_endpoint_returns_null_fields_when_provider_fails(
    auth_client, db_session, store_factory, open_meteo_app, respx_mock
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)
    respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(
        side_effect=httpx.TimeoutException("slow")
    )
    target = date.today() + timedelta(days=1)

    response = await auth_client.get(f"/api/weather/{store.id}/{target.isoformat()}")

    assert response.status_code == 200
    assert response.json() == {
        "weather": None,
        "weather_code": None,
        "temperature_max": None,
        "temperature_min": None,
        "precipitation": None,
    }


async def test_weather_endpoint_contains_unexpected_provider_failure(
    auth_client, db_session, store_factory
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)

    class BrokenWeatherService:
        async def get_daily(self, store, target):
            raise RuntimeError("unexpected provider failure")

    auth_client._transport.app.state.weather_service = BrokenWeatherService()
    target = date.today() + timedelta(days=1)

    response = await auth_client.get(f"/api/weather/{store.id}/{target.isoformat()}")

    assert response.status_code == 200
    assert all(value is None for value in response.json().values())


async def test_weather_endpoint_returns_normalized_success(
    auth_client, db_session, store_factory, open_meteo_app, respx_mock
) -> None:
    store = await _assign_store(auth_client, db_session, store_factory)
    target = date.today() + timedelta(days=1)
    respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(
            200,
            json={
                "daily": {
                    "time": [target.isoformat()],
                    "weather_code": [2],
                    "temperature_2m_max": [27.5],
                    "temperature_2m_min": [18.1],
                    "precipitation_sum": [0.2],
                }
            },
        )
    )

    response = await auth_client.get(f"/api/weather/{store.id}/{target.isoformat()}")

    assert response.status_code == 200
    assert response.json() == {
        "weather": "多云",
        "weather_code": 2,
        "temperature_max": 27.5,
        "temperature_min": 18.1,
        "precipitation": 0.2,
    }
