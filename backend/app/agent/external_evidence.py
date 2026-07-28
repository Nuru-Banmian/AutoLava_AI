from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
import json
from typing import Any, Literal, Protocol, TypeAlias

import httpx
from pydantic import BaseModel, ConfigDict, Field

from app.agent.contracts import (
    CurrentStoreScope,
    EvidencePeriodResult,
    ExternalEvidenceBundle,
    ExternalEvidenceCoverage,
    ExternalEvidenceFailure,
    ExternalEvidenceFreshness,
    ExternalGeographicScope,
)
from app.agent.runtime import RuntimeContext
from app.services.weather import weather_label

MAX_EXTERNAL_RESPONSE_BYTES = 256_000
MAX_EXTERNAL_ROWS = 366


def country_code_for_timezone(timezone_name: str) -> Literal["IT"] | None:
    """Return a backend-approved country scope without trusting model input."""

    return "IT" if timezone_name == "Europe/Rome" else None


class ExternalEvidenceLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    timezone: str = Field(min_length=1, max_length=64)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")


@dataclass(frozen=True)
class ExternalProviderPayload:
    facts: dict[str, Any]
    covered_dates: list[date]
    limitations: list[str] = field(default_factory=list)


ExternalFailureCategory: TypeAlias = Literal[
    "timeout",
    "rate_limited",
    "service_unavailable",
    "invalid_response",
]


class ExternalProviderFailure(RuntimeError):
    def __init__(self, category: ExternalFailureCategory) -> None:
        super().__init__(category)
        self.category = category


@dataclass(frozen=True)
class _CacheEntry:
    evidence: ExternalEvidenceBundle
    cached_at: datetime


class HistoricalWeatherProvider(Protocol):
    source: str

    async def fetch(
        self,
        location: ExternalEvidenceLocation,
        start: date,
        end: date,
    ) -> ExternalProviderPayload: ...


class PublicHolidayProvider(Protocol):
    source: str

    async def fetch(self, country_code: str, year: int) -> ExternalProviderPayload: ...


class OpenMeteoHistoricalWeatherProvider:
    source = "open_meteo_historical"
    endpoint = "https://archive-api.open-meteo.com/v1/archive"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    async def fetch(
        self,
        location: ExternalEvidenceLocation,
        start: date,
        end: date,
    ) -> ExternalProviderPayload:
        response_payload = await _fixed_get_json(
            self.client,
            self.endpoint,
            params={
                "latitude": location.latitude,
                "longitude": location.longitude,
                "start_date": start.isoformat(),
                "end_date": end.isoformat(),
                "timezone": location.timezone,
                "daily": "weather_code",
            },
        )
        try:
            daily = response_payload["daily"]
            rows = []
            covered_dates = []
            for raw_date, raw_code in zip(
                daily["time"],
                daily["weather_code"],
                strict=True,
            ):
                target_date = date.fromisoformat(str(raw_date))
                if not start <= target_date <= end:
                    raise ValueError("weather response exceeded requested period")
                code = int(raw_code)
                label = weather_label(code)
                if label is None:
                    raise ValueError("unsupported WMO weather code")
                covered_dates.append(target_date)
                rows.append(
                    {
                        "date": target_date.isoformat(),
                        "weather": label,
                        "weather_code": code,
                    }
                )
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalProviderFailure("invalid_response") from error
        return ExternalProviderPayload(
            facts={"days": rows},
            covered_dates=covered_dates,
            limitations=["历史天气是再分析数据，不等同于门店现场观测。"],
        )


class NagerPublicHolidayProvider:
    source = "nager_date_public_holidays"
    endpoint_prefix = "https://date.nager.at/api/v3/publicholidays"

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self.client = client

    async def fetch(self, country_code: str, year: int) -> ExternalProviderPayload:
        if country_code != "IT" or not 2000 <= year <= 2200:
            raise ExternalProviderFailure("invalid_response")
        response_payload = await _fixed_get_json(
            self.client,
            f"{self.endpoint_prefix}/{year}/{country_code}",
        )
        try:
            payload = response_payload
            if not isinstance(payload, list):
                raise TypeError("holiday response must be a list")
            holidays = []
            covered_dates = []
            for item in payload:
                if not isinstance(item, dict) or item["countryCode"] != country_code:
                    raise ValueError("holiday country scope mismatch")
                holiday_date = date.fromisoformat(str(item["date"]))
                covered_dates.append(holiday_date)
                holidays.append(
                    {
                        "date": holiday_date.isoformat(),
                        "local_name": str(item["localName"]),
                        "name": str(item["name"]),
                        "global": bool(item["global"]),
                        "subdivisions": [str(value) for value in item.get("counties") or []],
                        "types": [str(value) for value in item["types"]],
                    }
                )
        except (KeyError, TypeError, ValueError) as error:
            raise ExternalProviderFailure("invalid_response") from error
        return ExternalProviderPayload(
            facts={"holidays": holidays},
            covered_dates=covered_dates,
            limitations=["地区性假期只适用于供应方列出的行政区。"],
        )


class ExternalEvidenceService:
    def __init__(
        self,
        *,
        weather_provider: HistoricalWeatherProvider,
        holiday_provider: PublicHolidayProvider,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        max_age: timedelta = timedelta(days=1),
        max_cache_entries: int = 128,
    ) -> None:
        if not 1 <= max_cache_entries <= 1_024:
            raise ValueError("max_cache_entries must be between 1 and 1024")
        self.weather_provider = weather_provider
        self.holiday_provider = holiday_provider
        self.now = now
        self.max_age = max_age
        self.max_cache_entries = max_cache_entries
        self._cache: OrderedDict[tuple[object, ...], _CacheEntry] = OrderedDict()

    async def collect(
        self,
        evidence_type: str,
        context: RuntimeContext,
        *,
        start: date,
        end: date,
    ) -> ExternalEvidenceBundle:
        if evidence_type == "historical_weather":
            return await self.historical_weather(context, start=start, end=end)
        if evidence_type == "public_holidays":
            return await self.public_holidays(context, start=start, end=end)
        raise ValueError("unsupported external evidence type")

    async def historical_weather(
        self,
        context: RuntimeContext,
        *,
        start: date,
        end: date,
    ) -> ExternalEvidenceBundle:
        location = _location(context)
        queried_at = self.now()
        cache_key = (
            "historical_weather",
            context.store_id,
            location.latitude,
            location.longitude,
            location.timezone,
            start,
            end,
        )
        cached = self._cache.get(cache_key)
        if cached is not None and queried_at - cached.cached_at <= self.max_age:
            self._cache.move_to_end(cache_key)
            return _cached_evidence(cached, queried_at, cache_status="fresh")
        try:
            payload = await self.weather_provider.fetch(location, start, end)
            _validate_provider_payload(
                payload,
                evidence_type="historical_weather",
                start=start,
                end=end,
            )
        except ExternalProviderFailure as error:
            if cached is not None:
                return _stale_evidence(cached, queried_at, error.category)
            return _failed_evidence(
                context,
                start=start,
                end=end,
                evidence_type="historical_weather",
                source="open_meteo_historical",
                queried_at=queried_at,
                geographic_scope=ExternalGeographicScope(
                    kind="coordinates",
                    latitude=location.latitude,
                    longitude=location.longitude,
                    timezone=location.timezone,
                    country_code="IT",
                ),
                max_age=self.max_age,
                category=error.category,
            )
        except Exception:
            if cached is not None:
                return _stale_evidence(cached, queried_at, "service_unavailable")
            return _failed_evidence(
                context,
                start=start,
                end=end,
                evidence_type="historical_weather",
                source="open_meteo_historical",
                queried_at=queried_at,
                geographic_scope=ExternalGeographicScope(
                    kind="coordinates",
                    latitude=location.latitude,
                    longitude=location.longitude,
                    timezone=location.timezone,
                    country_code="IT",
                ),
                max_age=self.max_age,
                category="service_unavailable",
            )
        requested_dates = _dates(start, end)
        covered = set(payload.covered_dates)
        recorded_dates = len(covered.intersection(requested_dates))
        evidence = ExternalEvidenceBundle(
            status="ok",
            current_store=CurrentStoreScope(id=context.store_id),
            period=EvidencePeriodResult(start=start, end=end),
            evidence_type="historical_weather",
            source="open_meteo_historical",
            queried_at=queried_at,
            geographic_scope=ExternalGeographicScope(
                kind="coordinates",
                latitude=location.latitude,
                longitude=location.longitude,
                timezone=location.timezone,
                country_code="IT",
            ),
            coverage=ExternalEvidenceCoverage(
                calendar_dates=len(requested_dates),
                recorded_dates=recorded_dates,
                missing_dates=[day for day in requested_dates if day not in covered],
            ),
            freshness=ExternalEvidenceFreshness(
                status="fresh",
                as_of=queried_at,
                max_age_seconds=int(self.max_age.total_seconds()),
                cache_status="refreshed" if cached is not None else "miss",
            ),
            failure=ExternalEvidenceFailure(status="none"),
            result={
                "days": [
                    {
                        "date": item["date"],
                        "weather": item["weather"],
                    }
                    for item in payload.facts["days"]
                ]
            },
            warnings=payload.limitations,
            summary=(
                f"历史天气外部证据覆盖 {len(requested_dates)} 个日期中的 {recorded_dates} 个日期。"
            ),
        )
        self._store_cache(cache_key, evidence, queried_at)
        return evidence

    async def public_holidays(
        self,
        context: RuntimeContext,
        *,
        start: date,
        end: date,
    ) -> ExternalEvidenceBundle:
        if context.store_country_code is None:
            raise ValueError("external evidence country scope is unavailable")
        country_code = context.store_country_code
        if start.year != end.year:
            raise ValueError("public holiday evidence must stay within one calendar year")
        queried_at = self.now()
        cache_key = (
            "public_holidays",
            context.store_id,
            country_code,
            start,
            end,
        )
        cached = self._cache.get(cache_key)
        if cached is not None and queried_at - cached.cached_at <= self.max_age:
            self._cache.move_to_end(cache_key)
            return _cached_evidence(cached, queried_at, cache_status="fresh")
        try:
            payload = await self.holiday_provider.fetch(country_code, start.year)
            _validate_provider_payload(
                payload,
                evidence_type="public_holidays",
                start=date(start.year, 1, 1),
                end=date(start.year, 12, 31),
            )
        except ExternalProviderFailure as error:
            if cached is not None:
                return _stale_evidence(cached, queried_at, error.category)
            return _failed_evidence(
                context,
                start=start,
                end=end,
                evidence_type="public_holidays",
                source="nager_date_public_holidays",
                queried_at=queried_at,
                geographic_scope=ExternalGeographicScope(
                    kind="country",
                    timezone=context.store_timezone,
                    country_code="IT",
                ),
                max_age=self.max_age,
                category=error.category,
            )
        except Exception:
            if cached is not None:
                return _stale_evidence(cached, queried_at, "service_unavailable")
            return _failed_evidence(
                context,
                start=start,
                end=end,
                evidence_type="public_holidays",
                source="nager_date_public_holidays",
                queried_at=queried_at,
                geographic_scope=ExternalGeographicScope(
                    kind="country",
                    timezone=context.store_timezone,
                    country_code="IT",
                ),
                max_age=self.max_age,
                category="service_unavailable",
            )
        applicable_holidays = [
            item
            for item in payload.facts.get("holidays", [])
            if isinstance(item, dict)
            and isinstance(item.get("date"), str)
            and start <= date.fromisoformat(item["date"]) <= end
            and item.get("global") is True
        ]
        holidays = [
            {
                "date": item["date"],
                "local_name": item["local_name"],
                "name": item["name"],
            }
            for item in applicable_holidays
        ]
        requested_dates = _dates(start, end)
        warnings = list(payload.limitations)
        if any(
            isinstance(item, dict)
            and isinstance(item.get("date"), str)
            and start <= date.fromisoformat(item["date"]) <= end
            and item.get("global") is False
            for item in payload.facts.get("holidays", [])
        ):
            warnings.append("门店未配置行政区；地区性假期未纳入结果。")
        evidence = ExternalEvidenceBundle(
            status="ok",
            current_store=CurrentStoreScope(id=context.store_id),
            period=EvidencePeriodResult(start=start, end=end),
            evidence_type="public_holidays",
            source="nager_date_public_holidays",
            queried_at=queried_at,
            geographic_scope=ExternalGeographicScope(
                kind="country",
                timezone=context.store_timezone,
                country_code="IT",
            ),
            coverage=ExternalEvidenceCoverage(
                calendar_dates=len(requested_dates),
                recorded_dates=len(requested_dates),
                missing_dates=[],
            ),
            freshness=ExternalEvidenceFreshness(
                status="fresh",
                as_of=queried_at,
                max_age_seconds=int(self.max_age.total_seconds()),
                cache_status="refreshed" if cached is not None else "miss",
            ),
            failure=ExternalEvidenceFailure(status="none"),
            result={"holidays": holidays},
            warnings=warnings,
            summary=(
                f"公共假期外部证据覆盖 {start.year} 年 {start.month} 月，"
                f"共 {len(holidays)} 个假期。"
            ),
        )
        self._store_cache(cache_key, evidence, queried_at)
        return evidence

    def _store_cache(
        self,
        key: tuple[object, ...],
        evidence: ExternalEvidenceBundle,
        cached_at: datetime,
    ) -> None:
        self._cache[key] = _CacheEntry(evidence=evidence, cached_at=cached_at)
        self._cache.move_to_end(key)
        while len(self._cache) > self.max_cache_entries:
            self._cache.popitem(last=False)


def _location(context: RuntimeContext) -> ExternalEvidenceLocation:
    if (
        context.store_latitude is None
        or context.store_longitude is None
        or context.store_country_code is None
    ):
        raise ValueError("external evidence location is unavailable")
    return ExternalEvidenceLocation(
        latitude=context.store_latitude,
        longitude=context.store_longitude,
        timezone=context.store_timezone,
        country_code=context.store_country_code,
    )


def _dates(start: date, end: date) -> list[date]:
    if end < start:
        raise ValueError("external evidence end date must not precede start date")
    return [start + timedelta(days=offset) for offset in range((end - start).days + 1)]


async def _fixed_get_json(
    client: httpx.AsyncClient | None,
    url: str,
    *,
    params: dict[str, str | int | float | bool | None] | None = None,
) -> Any:
    try:
        if client is not None:
            return await _read_bounded_json(client, url, params=params)
        else:
            async with httpx.AsyncClient() as owned_client:
                return await _read_bounded_json(owned_client, url, params=params)
    except httpx.TimeoutException as error:
        raise ExternalProviderFailure("timeout") from error
    except httpx.RequestError as error:
        raise ExternalProviderFailure("service_unavailable") from error


async def _read_bounded_json(
    client: httpx.AsyncClient,
    url: str,
    *,
    params: dict[str, str | int | float | bool | None] | None,
) -> Any:
    request = client.build_request("GET", url, params=params, timeout=8)
    response = await client.send(request, stream=True)
    try:
        if response.status_code == 429:
            raise ExternalProviderFailure("rate_limited")
        if response.status_code >= 500:
            raise ExternalProviderFailure("service_unavailable")
        if response.status_code >= 400:
            raise ExternalProviderFailure("invalid_response")
        declared_length = response.headers.get("content-length")
        if (
            declared_length is not None
            and declared_length.isdecimal()
            and int(declared_length) > MAX_EXTERNAL_RESPONSE_BYTES
        ):
            raise ExternalProviderFailure("invalid_response")
        body = bytearray()
        async for chunk in response.aiter_bytes():
            body.extend(chunk)
            if len(body) > MAX_EXTERNAL_RESPONSE_BYTES:
                raise ExternalProviderFailure("invalid_response")
        try:
            return json.loads(body)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ExternalProviderFailure("invalid_response") from error
    finally:
        await response.aclose()


def _validate_provider_payload(
    payload: ExternalProviderPayload,
    *,
    evidence_type: str,
    start: date,
    end: date,
) -> None:
    key = "days" if evidence_type == "historical_weather" else "holidays"
    rows = payload.facts.get(key)
    max_rows = min(MAX_EXTERNAL_ROWS, (end - start).days + 1)
    try:
        encoded = json.dumps(payload.facts, ensure_ascii=False).encode()
    except (TypeError, ValueError) as error:
        raise ExternalProviderFailure("invalid_response") from error
    try:
        row_dates = (
            [date.fromisoformat(str(item["date"])) for item in rows if isinstance(item, dict)]
            if isinstance(rows, list)
            else []
        )
    except (KeyError, ValueError) as error:
        raise ExternalProviderFailure("invalid_response") from error
    rows_have_required_fields = bool(
        isinstance(rows, list)
        and all(
            isinstance(item, dict)
            and isinstance(item.get("date"), str)
            and (
                isinstance(item.get("weather"), str)
                if evidence_type == "historical_weather"
                else isinstance(item.get("local_name"), str)
                and isinstance(item.get("name"), str)
                and isinstance(item.get("global"), bool)
            )
            for item in rows
        )
    )
    row_count = len(rows) if isinstance(rows, list) else max_rows + 1
    if (
        not rows_have_required_fields
        or row_count > max_rows
        or len(payload.covered_dates) > max_rows
        or len(row_dates) != row_count
        or len(set(row_dates)) != len(row_dates)
        or set(row_dates) != set(payload.covered_dates)
        or len(encoded) > MAX_EXTERNAL_RESPONSE_BYTES
        or len(payload.limitations) > 20
        or any(len(value) > 500 for value in payload.limitations)
        or any(not start <= value <= end for value in payload.covered_dates)
    ):
        raise ExternalProviderFailure("invalid_response")


def _cached_evidence(
    cached: _CacheEntry,
    queried_at: datetime,
    *,
    cache_status: str,
) -> ExternalEvidenceBundle:
    return cached.evidence.model_copy(
        update={
            "queried_at": queried_at,
            "freshness": cached.evidence.freshness.model_copy(
                update={
                    "status": "fresh",
                    "cache_status": cache_status,
                    "refresh_failure": None,
                }
            ),
        }
    )


def _stale_evidence(
    cached: _CacheEntry,
    queried_at: datetime,
    category: ExternalFailureCategory,
) -> ExternalEvidenceBundle:
    reason = {
        "timeout": "超时",
        "rate_limited": "供应方限流",
        "service_unavailable": "服务不可用",
        "invalid_response": "响应无效",
    }[category]
    warning = f"缓存已过期；刷新因{reason}失败，结果仅供有限参考。"
    return cached.evidence.model_copy(
        update={
            "queried_at": queried_at,
            "freshness": cached.evidence.freshness.model_copy(
                update={
                    "status": "stale",
                    "cache_status": "stale_fallback",
                    "refresh_failure": category,
                }
            ),
            "warnings": [*cached.evidence.warnings, warning][-20:],
        }
    )


def _failed_evidence(
    context: RuntimeContext,
    *,
    start: date,
    end: date,
    evidence_type: str,
    source: str,
    queried_at: datetime,
    geographic_scope: ExternalGeographicScope,
    max_age: timedelta,
    category: str,
) -> ExternalEvidenceBundle:
    requested_dates = _dates(start, end)
    return ExternalEvidenceBundle.model_validate(
        {
            "status": "failed",
            "current_store": {"id": context.store_id},
            "period": {"start": start, "end": end},
            "evidence_type": evidence_type,
            "source": source,
            "queried_at": queried_at,
            "geographic_scope": geographic_scope,
            "coverage": {
                "calendar_dates": len(requested_dates),
                "recorded_dates": 0,
                "missing_dates": requested_dates,
            },
            "freshness": {
                "status": "unavailable",
                "as_of": None,
                "max_age_seconds": int(max_age.total_seconds()),
                "cache_status": "miss",
                "refresh_failure": category,
            },
            "failure": {
                "status": "failed",
                "category": category,
                "message": "外部证据供应方暂时不可用",
            },
            "result": {},
            "warnings": ["外部证据查询失败；未返回任何外部事实。"],
            "summary": "外部经营证据暂时不可用。",
        }
    )
