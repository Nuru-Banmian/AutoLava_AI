from dataclasses import dataclass
from datetime import date, datetime
from typing import Any, Protocol
from zoneinfo import ZoneInfo

import httpx

from app.models.identity import Store


class WeatherLocation(Protocol):
    id: int
    latitude: Any
    longitude: Any
    timezone: str


@dataclass(frozen=True)
class FrozenWeatherLocation:
    id: int
    latitude: Any
    longitude: Any
    timezone: str

    @classmethod
    def from_store(cls, store: Store) -> "FrozenWeatherLocation":
        return cls(
            id=store.id,
            latitude=store.latitude,
            longitude=store.longitude,
            timezone=store.timezone,
        )


@dataclass(frozen=True)
class WeatherResult:
    weather: str
    weather_code: int
    temperature_max: float
    temperature_min: float
    precipitation: float


def weather_label(code: int) -> str | None:
    return {
        0: "晴",
        1: "少云",
        2: "多云",
        3: "阴",
        45: "雾",
        48: "冻雾",
        51: "小毛毛雨",
        53: "毛毛雨",
        55: "大毛毛雨",
        56: "小冻毛毛雨",
        57: "冻毛毛雨",
        61: "小雨",
        63: "中雨",
        65: "大雨",
        66: "小冻雨",
        67: "冻雨",
        71: "小雪",
        73: "中雪",
        75: "大雪",
        77: "雪粒",
        80: "小阵雨",
        81: "阵雨",
        82: "大阵雨",
        85: "小阵雪",
        86: "大阵雪",
        95: "雷雨",
        96: "雷雨伴小冰雹",
        99: "雷雨伴大冰雹",
    }.get(code)


class WeatherProvider(Protocol):
    async def get_daily(
        self, store: WeatherLocation, target: date
    ) -> WeatherResult | None: ...


class OpenMeteoProvider:
    def __init__(self, client: httpx.AsyncClient | None = None):
        self.client = client

    async def _get(self, url: str, **kwargs: Any) -> httpx.Response:
        if self.client is not None:
            return await self.client.get(url, **kwargs)
        async with httpx.AsyncClient() as client:
            return await client.get(url, **kwargs)

    async def get_daily(
        self, store: WeatherLocation, target: date
    ) -> WeatherResult | None:
        today = datetime.now(ZoneInfo(store.timezone)).date()
        base = (
            "https://api.open-meteo.com/v1/forecast"
            if target >= today
            else "https://archive-api.open-meteo.com/v1/archive"
        )
        params = {
            "latitude": float(store.latitude),
            "longitude": float(store.longitude),
            "start_date": target.isoformat(),
            "end_date": target.isoformat(),
            "timezone": store.timezone,
            "daily": ("weather_code,temperature_2m_max,temperature_2m_min,precipitation_sum"),
        }
        try:
            response = await self._get(base, params=params, timeout=8)
            response.raise_for_status()
            daily = response.json()["daily"]
            code = int(daily["weather_code"][0])
            label = weather_label(code)
            if label is None:
                return None
            return WeatherResult(
                weather=label,
                weather_code=code,
                temperature_max=float(daily["temperature_2m_max"][0]),
                temperature_min=float(daily["temperature_2m_min"][0]),
                precipitation=float(daily["precipitation_sum"][0]),
            )
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError):
            return None

    async def geocode(self, query: str) -> list[dict[str, str | float]]:
        try:
            response = await self._get(
                "https://geocoding-api.open-meteo.com/v1/search",
                params={"name": query.strip(), "count": 10, "language": "zh", "format": "json"},
                timeout=8,
            )
            response.raise_for_status()
            candidates = []
            for item in response.json().get("results", []):
                candidates.append(
                    {
                        "name": str(item["name"]),
                        "latitude": float(item["latitude"]),
                        "longitude": float(item["longitude"]),
                        "country": str(item["country"]),
                        "timezone": str(item["timezone"]),
                    }
                )
            return candidates
        except Exception:
            return []

    async def timezone(self, latitude: float, longitude: float) -> str | None:
        """Resolve coordinates without exposing the provider to API or UI callers."""
        try:
            response = await self._get(
                "https://api.open-meteo.com/v1/forecast",
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "timezone": "auto",
                    "forecast_days": 1,
                },
                timeout=8,
            )
            response.raise_for_status()
            timezone = str(response.json()["timezone"])
            ZoneInfo(timezone)
            return timezone
        except (httpx.HTTPError, KeyError, TypeError, ValueError):
            return None


class WeatherService:
    def __init__(self, primary: WeatherProvider, fallback: WeatherProvider | None = None):
        self.primary = primary
        self.fallback = fallback

    async def get_daily(
        self, store: WeatherLocation, target: date
    ) -> WeatherResult | None:
        try:
            result = await self.primary.get_daily(store, target)
        except Exception:
            result = None
        if result is not None or self.fallback is None:
            return result
        try:
            return await self.fallback.get_daily(store, target)
        except Exception:
            return None
