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
    assert result.weather == "雨"
    assert route.called


async def test_weather_failure_returns_none(weather_service, respx_mock, store) -> None:
    respx_mock.get("https://api.open-meteo.com/v1/forecast").mock(
        side_effect=httpx.TimeoutException("slow")
    )

    assert await weather_service.get_daily(store, date.today() + timedelta(days=1)) is None


async def test_weather_service_contains_primary_and_fallback_exceptions(store) -> None:
    class BrokenProvider:
        async def get_daily(self, store, target):
            raise RuntimeError("provider failed unexpectedly")

    service = WeatherService(BrokenProvider(), BrokenProvider())

    assert await service.get_daily(store, date.today()) is None


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
    assert await provider.geocode("Milano") == []


@pytest.mark.parametrize(
    ("code", "label"),
    [(0, "晴"), (2, "多云"), (45, "雾"), (63, "雨"), (75, "雪"), (95, "雷雨"), (500, "未知")],
)
def test_weather_label_is_stable(code: int, label: str) -> None:
    assert weather_label(code) == label
