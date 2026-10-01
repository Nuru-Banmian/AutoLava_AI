import asyncio
from datetime import date, timedelta
from decimal import Decimal

import httpx
import pytest

from app.models.identity import Store
from app.services.weather import OpenMeteoProvider, WeatherService, weather_label


@pytest.fixture
def store() -> Store:
    return Store(
        id=1,
        name="Berlin",
        address="Test",
        latitude=Decimal("52.520000"),
        longitude=Decimal("13.405000"),
        timezone="Europe/Berlin",
        is_active=True,
    )


@pytest.fixture
def weather_service() -> WeatherService:
    return WeatherService(OpenMeteoProvider(httpx.AsyncClient()))


async def test_forecast_maps_open_meteo_day(weather_service, respx_mock, store) -> None:
    target = date.today() + timedelta(days=1)
    route = respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(
        return_value=httpx.Response(
            200,
            json={
                "daily": {
                    "time": [target.isoformat()],
                    "weather_code": [0],
                    "temperature_2m_max": [31.2],
                    "temperature_2m_min": [20.1],
                    "precipitation_sum": [0.0],
                }
            },
        )
    )

    result = await weather_service.get_daily(store, target)

    assert result is not None
    assert result.weather == "晴"
    assert result.weather_code == 0
    assert route.calls[0].request.url.params["timezone"] == "Europe/Berlin"


async def test_past_day_uses_archive_endpoint(weather_service, respx_mock, store) -> None:
    target = date(2020, 7, 13)
    route = respx_mock.get("https://archive-api.open-meteo.com/v1/archive").mock(
        return_value=httpx.Response(
            200,
            json={
                "daily": {
                    "time": [target.isoformat()],
                    "weather_code": [61],
                    "temperature_2m_max": [18.0],
                    "temperature_2m_min": [10.0],
                    "precipitation_sum": [4.2],
                }
            },
        )
    )

    result = await weather_service.get_daily(store, target)

    assert result is not None
    assert result.weather == "小雨"
    assert route.called


async def test_weather_failure_returns_none(weather_service, respx_mock, store) -> None:
    respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(
        side_effect=httpx.TimeoutException("slow")
    )

    assert await weather_service.get_daily(store, date.today() + timedelta(days=1)) is None


async def test_all_provider_entrypoints_share_actual_network_limit(store) -> None:
    active = 0
    peak = 0
    two_entered = asyncio.Event()
    release = asyncio.Event()

    async def respond(request: httpx.Request) -> httpx.Response:
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        if active == 2:
            two_entered.set()
        try:
            await release.wait()
            if "geocoding" in str(request.url):
                return httpx.Response(200, json={"results": []})
            return httpx.Response(200, json={"daily": {
                "weather_code": [0],
                "temperature_2m_max": [20],
                "temperature_2m_min": [10],
                "precipitation_sum": [0],
            }})
        finally:
            active -= 1

    client = httpx.AsyncClient(transport=httpx.MockTransport(respond))
    provider = OpenMeteoProvider(client, max_inflight=2)
    calls = [
        asyncio.create_task(provider.get_daily(store, date(2020, 1, day)))
        for day in range(1, 7)
    ]
    calls.append(asyncio.create_task(provider.geocode("Berlin")))
    try:
        await asyncio.wait_for(two_entered.wait(), timeout=2)
        assert peak == 2
        release.set()
        await asyncio.wait_for(asyncio.gather(*calls), timeout=3)
        assert peak == 2
        assert active == 0
    finally:
        release.set()
        await provider.aclose()
    assert client.is_closed


async def test_weather_service_does_not_hide_program_errors(store) -> None:
    class BrokenProvider:
        async def get_daily(self, store, target):
            raise RuntimeError("provider failed unexpectedly")

    service = WeatherService(BrokenProvider(), BrokenProvider())

    with pytest.raises(RuntimeError, match="provider failed unexpectedly"):
        await service.get_daily(store, date.today())


async def test_geocode_normalizes_candidates_and_failure_is_empty(respx_mock) -> None:
    provider = OpenMeteoProvider(httpx.AsyncClient())
    route = respx_mock.get("https://geocoding-api.open-meteo.com/v1/search").mock(
        return_value=httpx.Response(
            200,
            json={
                "results": [
                    {
                        "name": "Milano",
                        "latitude": 45.46,
                        "longitude": 9.19,
                        "country": "Italia",
                        "timezone": "Europe/Rome",
                        "ignored": "value",
                    }
                ]
            },
        )
    )

    assert await provider.geocode(" Milano ") == [
        {
            "name": "Milano",
            "latitude": 45.46,
            "longitude": 9.19,
            "country": "Italia",
            "timezone": "Europe/Rome",
        }
    ]
    assert route.calls[0].request.url.params["name"] == "Milano"

    route.mock(side_effect=httpx.ConnectError("offline"))
    assert await provider.geocode("Milano") == []

    route.mock(side_effect=RuntimeError("unexpected provider failure"))
    with pytest.raises(RuntimeError, match="unexpected provider failure"):
        await provider.geocode("Milano")


@pytest.mark.parametrize(
    ("code", "label"),
    [
        (0, "晴"), (1, "少云"), (2, "多云"), (3, "阴"),
        (45, "雾"), (48, "冻雾"),
        (51, "小毛毛雨"), (53, "毛毛雨"), (55, "大毛毛雨"),
        (56, "小冻毛毛雨"), (57, "冻毛毛雨"),
        (61, "小雨"), (63, "中雨"), (65, "大雨"),
        (66, "小冻雨"), (67, "冻雨"),
        (71, "小雪"), (73, "中雪"), (75, "大雪"), (77, "雪粒"),
        (80, "小阵雨"), (81, "阵雨"), (82, "大阵雨"),
        (85, "小阵雪"), (86, "大阵雪"),
        (95, "雷雨"), (96, "雷雨伴小冰雹"), (99, "雷雨伴大冰雹"),
        (500, None),
    ],
)
def test_weather_label_is_stable(code: int, label: str | None) -> None:
    assert weather_label(code) == label
