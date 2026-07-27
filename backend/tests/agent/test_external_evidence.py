from datetime import date, datetime, timedelta, timezone

import pytest
import httpx

from app.agent.answer_grounding import NativeAnswerClaim, answer_is_grounded
from app.agent.external_evidence import (
    ExternalEvidenceLocation,
    ExternalEvidenceService,
    ExternalProviderFailure,
    ExternalProviderPayload,
    NagerPublicHolidayProvider,
    OpenMeteoHistoricalWeatherProvider,
)
from app.agent.conversation import ConversationState
from app.agent.contracts import ModelMessage
from app.agent.native import (
    FakeNativeToolModel,
    NativeToolAgentService,
    NativeToolAccessDenied,
)
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags


NOW = datetime(2026, 7, 28, 10, 0, tzinfo=timezone.utc)


def _context() -> RuntimeContext:
    return RuntimeContext(
        user_id=7,
        store_id=11,
        role="admin",
        store_timezone="Europe/Rome",
        store_latitude=45.4642,
        store_longitude=9.1900,
        store_country_code="IT",
        features=RuntimeFeatureFlags(
            agent_enabled=True,
            company_settlement_enabled=False,
            income_items_enabled=False,
            wash_count_enabled=True,
        ),
    )


class StaticScopeResolver:
    async def refresh(self, context: RuntimeContext) -> RuntimeContext:
        return context


class RecordingWeatherProvider:
    source = "open_meteo_historical"

    def __init__(self) -> None:
        self.calls: list[tuple[ExternalEvidenceLocation, date, date]] = []

    async def fetch(
        self,
        location: ExternalEvidenceLocation,
        start: date,
        end: date,
    ) -> ExternalProviderPayload:
        self.calls.append((location, start, end))
        return ExternalProviderPayload(
            facts={
                "days": [
                    {
                        "date": start.isoformat(),
                        "weather": "多云",
                        "weather_code": 2,
                    }
                ]
            },
            covered_dates=[start],
            limitations=["历史天气是再分析数据，不等同于门店现场观测。"],
        )


class UnusedHolidayProvider:
    source = "nager_date_public_holidays"

    async def fetch(self, country_code: str, year: int) -> ExternalProviderPayload:
        raise AssertionError("holiday provider must not be called")


class UnusedWeatherProvider:
    source = "open_meteo_historical"

    async def fetch(
        self,
        location: ExternalEvidenceLocation,
        start: date,
        end: date,
    ) -> ExternalProviderPayload:
        raise AssertionError("weather provider must not be called")


class RecordingHolidayProvider:
    source = "nager_date_public_holidays"

    def __init__(self) -> None:
        self.calls: list[tuple[str, int]] = []

    async def fetch(self, country_code: str, year: int) -> ExternalProviderPayload:
        self.calls.append((country_code, year))
        return ExternalProviderPayload(
            facts={
                "holidays": [
                    {
                        "date": "2026-07-01",
                        "local_name": "Festività locale",
                        "name": "Local Holiday",
                        "global": False,
                        "subdivisions": ["IT-25"],
                        "types": ["Public"],
                    },
                    {
                        "date": "2026-07-02",
                        "local_name": "Festa nazionale",
                        "name": "National Holiday",
                        "global": True,
                        "subdivisions": [],
                        "types": ["Public"],
                    },
                    {
                        "date": "2026-08-15",
                        "local_name": "Ferragosto",
                        "name": "Assumption Day",
                        "global": True,
                        "subdivisions": [],
                        "types": ["Public"],
                    },
                ]
            },
            covered_dates=[
                date(2026, 7, 1),
                date(2026, 7, 2),
                date(2026, 8, 15),
            ],
            limitations=["地区性假期只适用于供应方列出的行政区。"],
        )


class SequencedHolidayProvider(RecordingHolidayProvider):
    def __init__(self) -> None:
        super().__init__()
        self.failure: str | None = None

    async def fetch(self, country_code: str, year: int) -> ExternalProviderPayload:
        if self.failure is not None:
            raise ExternalProviderFailure(self.failure)
        return await super().fetch(country_code, year)


async def test_historical_weather_returns_a_complete_external_evidence_record() -> None:
    weather = RecordingWeatherProvider()
    service = ExternalEvidenceService(
        weather_provider=weather,
        holiday_provider=UnusedHolidayProvider(),
        now=lambda: NOW,
    )

    evidence = await service.historical_weather(
        _context(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
    )

    assert weather.calls == [
        (
            ExternalEvidenceLocation(
                latitude=45.4642,
                longitude=9.19,
                timezone="Europe/Rome",
                country_code="IT",
            ),
            date(2026, 7, 1),
            date(2026, 7, 31),
        )
    ]
    assert evidence.model_dump(mode="json") == {
        "status": "ok",
        "current_store": {"id": 11},
        "period": {"start": "2026-07-01", "end": "2026-07-31"},
        "evidence_type": "historical_weather",
        "external_evidence": True,
        "unit": "external_fact",
        "source": "open_meteo_historical",
        "queried_at": "2026-07-28T10:00:00Z",
        "geographic_scope": {
            "kind": "coordinates",
            "latitude": 45.4642,
            "longitude": 9.19,
            "timezone": "Europe/Rome",
            "country_code": "IT",
        },
        "coverage": {
            "calendar_dates": 31,
            "recorded_dates": 1,
            "missing_dates": [f"2026-07-{day:02d}" for day in range(2, 32)],
        },
        "freshness": {
            "status": "fresh",
            "as_of": "2026-07-28T10:00:00Z",
            "max_age_seconds": 86400,
            "cache_status": "miss",
            "refresh_failure": None,
        },
        "failure": {
            "status": "none",
            "category": None,
            "message": None,
        },
        "result": {
            "days": [
                {
                    "date": "2026-07-01",
                    "weather": "多云",
                }
            ]
        },
        "warnings": ["历史天气是再分析数据，不等同于门店现场观测。"],
        "truncated": False,
        "summary": "历史天气外部证据覆盖 31 个日期中的 1 个日期。",
    }


async def test_public_holidays_are_filtered_to_the_approved_country_and_period() -> None:
    holidays = RecordingHolidayProvider()
    service = ExternalEvidenceService(
        weather_provider=UnusedWeatherProvider(),
        holiday_provider=holidays,
        now=lambda: NOW,
    )

    evidence = await service.public_holidays(
        _context(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
    )

    assert holidays.calls == [("IT", 2026)]
    assert evidence.evidence_type == "public_holidays"
    assert evidence.source == "nager_date_public_holidays"
    assert evidence.external_evidence is True
    assert evidence.geographic_scope.model_dump() == {
        "kind": "country",
        "latitude": None,
        "longitude": None,
        "timezone": "Europe/Rome",
        "country_code": "IT",
    }
    assert evidence.coverage.calendar_dates == 31
    assert evidence.coverage.recorded_dates == 31
    assert evidence.coverage.missing_dates == []
    assert evidence.result == {
        "holidays": [
            {
                "date": "2026-07-02",
                "local_name": "Festa nazionale",
                "name": "National Holiday",
            }
        ]
    }
    assert evidence.warnings == [
        "地区性假期只适用于供应方列出的行政区。",
        "门店未配置行政区；地区性假期未纳入结果。",
    ]
    assert evidence.summary == "公共假期外部证据覆盖 2026 年 7 月，共 1 个假期。"


class FailingWeatherProvider:
    source = "open_meteo_historical"

    def __init__(self, category: str) -> None:
        self.category = category

    async def fetch(
        self,
        location: ExternalEvidenceLocation,
        start: date,
        end: date,
    ) -> ExternalProviderPayload:
        raise ExternalProviderFailure(self.category)


@pytest.mark.parametrize(
    "category",
    ["timeout", "rate_limited", "service_unavailable"],
)
async def test_external_provider_failures_are_explicit_and_return_no_facts(
    category: str,
) -> None:
    service = ExternalEvidenceService(
        weather_provider=FailingWeatherProvider(category),
        holiday_provider=UnusedHolidayProvider(),
        now=lambda: NOW,
    )

    evidence = await service.historical_weather(
        _context(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
    )

    assert evidence.status == "failed"
    assert evidence.result == {}
    assert evidence.coverage.recorded_dates == 0
    assert evidence.freshness.status == "unavailable"
    assert evidence.freshness.cache_status == "miss"
    assert evidence.freshness.refresh_failure == category
    assert evidence.failure.model_dump() == {
        "status": "failed",
        "category": category,
        "message": "外部证据供应方暂时不可用",
    }


class SequencedWeatherProvider(RecordingWeatherProvider):
    def __init__(self) -> None:
        super().__init__()
        self.failure: str | None = None

    async def fetch(
        self,
        location: ExternalEvidenceLocation,
        start: date,
        end: date,
    ) -> ExternalProviderPayload:
        if self.failure is not None:
            raise ExternalProviderFailure(self.failure)
        return await super().fetch(location, start, end)


async def test_stale_cache_refresh_failure_returns_marked_stale_evidence() -> None:
    clock = [NOW]
    weather = SequencedWeatherProvider()
    service = ExternalEvidenceService(
        weather_provider=weather,
        holiday_provider=UnusedHolidayProvider(),
        now=lambda: clock[0],
        max_age=timedelta(hours=1),
    )
    first = await service.historical_weather(
        _context(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
    )
    clock[0] += timedelta(hours=2)
    weather.failure = "rate_limited"

    stale = await service.historical_weather(
        _context(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
    )

    assert stale.status == "ok"
    assert stale.result == first.result
    assert stale.queried_at == clock[0]
    assert stale.freshness.status == "stale"
    assert stale.freshness.as_of == NOW
    assert stale.freshness.cache_status == "stale_fallback"
    assert stale.freshness.refresh_failure == "rate_limited"
    assert stale.failure.status == "none"
    assert stale.warnings[-1] == "缓存已过期；刷新因供应方限流失败，结果仅供有限参考。"


async def test_fresh_cache_avoids_provider_and_stale_cache_can_refresh() -> None:
    clock = [NOW]
    weather = SequencedWeatherProvider()
    service = ExternalEvidenceService(
        weather_provider=weather,
        holiday_provider=UnusedHolidayProvider(),
        now=lambda: clock[0],
        max_age=timedelta(hours=1),
    )
    query = {
        "start": date(2026, 7, 1),
        "end": date(2026, 7, 31),
    }
    await service.historical_weather(_context(), **query)
    clock[0] += timedelta(minutes=30)
    fresh = await service.historical_weather(_context(), **query)
    clock[0] += timedelta(hours=1)
    refreshed = await service.historical_weather(_context(), **query)

    assert len(weather.calls) == 2
    assert fresh.freshness.cache_status == "fresh"
    assert fresh.freshness.as_of == NOW
    assert refreshed.freshness.cache_status == "refreshed"
    assert refreshed.freshness.as_of == clock[0]


async def test_external_cache_never_reuses_another_store_scope() -> None:
    weather = SequencedWeatherProvider()
    service = ExternalEvidenceService(
        weather_provider=weather,
        holiday_provider=UnusedHolidayProvider(),
        now=lambda: NOW,
    )
    query = {
        "start": date(2026, 7, 1),
        "end": date(2026, 7, 31),
    }

    first = await service.historical_weather(_context(), **query)
    second = await service.historical_weather(
        RuntimeContext.model_validate(
            {
                **_context().model_dump(),
                "store_id": 12,
            }
        ),
        **query,
    )

    assert first.current_store.id == 11
    assert second.current_store.id == 12
    assert len(weather.calls) == 2


async def test_external_cache_has_a_backend_enforced_capacity() -> None:
    weather = SequencedWeatherProvider()
    service = ExternalEvidenceService(
        weather_provider=weather,
        holiday_provider=UnusedHolidayProvider(),
        now=lambda: NOW,
        max_cache_entries=1,
    )

    await service.historical_weather(
        _context(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
    )
    await service.historical_weather(
        _context(),
        start=date(2026, 6, 1),
        end=date(2026, 6, 30),
    )
    await service.historical_weather(
        _context(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
    )

    assert len(weather.calls) == 3


async def test_public_holiday_cache_has_the_same_stale_fallback_semantics() -> None:
    clock = [NOW]
    holidays = SequencedHolidayProvider()
    service = ExternalEvidenceService(
        weather_provider=UnusedWeatherProvider(),
        holiday_provider=holidays,
        now=lambda: clock[0],
        max_age=timedelta(hours=1),
    )
    query = {
        "start": date(2026, 7, 1),
        "end": date(2026, 7, 31),
    }
    first = await service.public_holidays(_context(), **query)
    clock[0] += timedelta(hours=2)
    holidays.failure = "timeout"
    stale = await service.public_holidays(_context(), **query)

    assert stale.result == first.result
    assert stale.freshness.status == "stale"
    assert stale.freshness.cache_status == "stale_fallback"
    assert stale.freshness.refresh_failure == "timeout"
    assert stale.warnings[-1] == "缓存已过期；刷新因超时失败，结果仅供有限参考。"


async def test_open_meteo_adapter_uses_only_the_approved_archive_endpoint(
    respx_mock,
) -> None:
    route = respx_mock.get("https://archive-api.open-meteo.com/v1/archive").mock(
        return_value=httpx.Response(
            200,
            json={
                "daily": {
                    "time": ["2026-07-01"],
                    "weather_code": [2],
                    "temperature_2m_max": [29.5],
                    "temperature_2m_min": [20],
                    "precipitation_sum": [0.2],
                }
            },
        )
    )
    async with httpx.AsyncClient() as client:
        provider = OpenMeteoHistoricalWeatherProvider(client=client)
        result = await provider.fetch(
            ExternalEvidenceLocation(
                latitude=45.4642,
                longitude=9.19,
                timezone="Europe/Rome",
                country_code="IT",
            ),
            date(2026, 7, 1),
            date(2026, 7, 1),
        )

    assert result.covered_dates == [date(2026, 7, 1)]
    assert result.facts["days"][0]["weather"] == "多云"
    assert dict(route.calls[0].request.url.params) == {
        "latitude": "45.4642",
        "longitude": "9.19",
        "start_date": "2026-07-01",
        "end_date": "2026-07-01",
        "timezone": "Europe/Rome",
        "daily": "weather_code",
    }
    assert "authorization" not in route.calls[0].request.headers


async def test_nager_adapter_uses_only_the_approved_country_year_endpoint(
    respx_mock,
) -> None:
    route = respx_mock.get("https://date.nager.at/api/v3/publicholidays/2026/IT").mock(
        return_value=httpx.Response(
            200,
            json=[
                {
                    "date": "2026-08-15",
                    "localName": "Ferragosto",
                    "name": "Assumption Day",
                    "countryCode": "IT",
                    "global": True,
                    "counties": None,
                    "types": ["Public"],
                }
            ],
        )
    )
    async with httpx.AsyncClient() as client:
        result = await NagerPublicHolidayProvider(client=client).fetch("IT", 2026)

    assert route.called
    assert result.covered_dates == [date(2026, 8, 15)]
    assert result.facts == {
        "holidays": [
            {
                "date": "2026-08-15",
                "local_name": "Ferragosto",
                "name": "Assumption Day",
                "global": True,
                "subdivisions": [],
                "types": ["Public"],
            }
        ]
    }
    assert "authorization" not in route.calls[0].request.headers


@pytest.mark.parametrize(
    ("status_code", "category"),
    [(429, "rate_limited"), (503, "service_unavailable")],
)
async def test_http_adapters_classify_retryable_provider_failures(
    respx_mock,
    status_code: int,
    category: str,
) -> None:
    respx_mock.get("https://archive-api.open-meteo.com/v1/archive").mock(
        return_value=httpx.Response(status_code)
    )
    async with httpx.AsyncClient() as client:
        provider = OpenMeteoHistoricalWeatherProvider(client=client)
        with pytest.raises(ExternalProviderFailure) as raised:
            await provider.fetch(
                ExternalEvidenceLocation(
                    latitude=45.4642,
                    longitude=9.19,
                    timezone="Europe/Rome",
                    country_code="IT",
                ),
                date(2026, 7, 1),
                date(2026, 7, 31),
            )
    assert raised.value.category == category


async def test_http_adapter_classifies_timeout_without_live_network(respx_mock) -> None:
    respx_mock.get("https://archive-api.open-meteo.com/v1/archive").mock(
        side_effect=httpx.ReadTimeout("local deterministic timeout")
    )
    async with httpx.AsyncClient() as client:
        provider = OpenMeteoHistoricalWeatherProvider(client=client)
        with pytest.raises(ExternalProviderFailure) as raised:
            await provider.fetch(
                ExternalEvidenceLocation(
                    latitude=45.4642,
                    longitude=9.19,
                    timezone="Europe/Rome",
                    country_code="IT",
                ),
                date(2026, 7, 1),
                date(2026, 7, 31),
            )
    assert raised.value.category == "timeout"


async def test_http_adapter_rejects_an_oversized_response(respx_mock) -> None:
    respx_mock.get("https://archive-api.open-meteo.com/v1/archive").mock(
        return_value=httpx.Response(200, content=b"x" * 256_001)
    )
    async with httpx.AsyncClient() as client:
        provider = OpenMeteoHistoricalWeatherProvider(client=client)
        with pytest.raises(ExternalProviderFailure) as raised:
            await provider.fetch(
                ExternalEvidenceLocation(
                    latitude=45.4642,
                    longitude=9.19,
                    timezone="Europe/Rome",
                    country_code="IT",
                ),
                date(2026, 7, 1),
                date(2026, 7, 31),
            )
    assert raised.value.category == "invalid_response"


async def test_native_catalog_exposes_bounded_external_tools_with_external_envelopes() -> None:
    external = ExternalEvidenceService(
        weather_provider=RecordingWeatherProvider(),
        holiday_provider=RecordingHolidayProvider(),
        now=lambda: NOW,
    )
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "补充外部经营证据。"},
                "tool_calls": [
                    {
                        "id": "weather-1",
                        "name": "historical_weather",
                        "arguments": {"year": 2026, "month": 7},
                    },
                    {
                        "id": "holiday-1",
                        "name": "public_holidays",
                        "arguments": {"year": 2026, "month": 7},
                    },
                ],
                "signal": "continue",
            },
            {
                "message": {"role": "assistant", "content": "外部证据已返回。"},
                "signal": "end",
            },
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=object(),
        external_evidence_collector=external,
        scope_resolver=StaticScopeResolver(),
        now=lambda: NOW,
    )

    result = await service.run(
        _context(),
        ConversationState(),
        [ModelMessage(role="user", content="调查 2026 年 7 月的天气和公共假期。")],
    )

    catalog = {tool.name: tool for tool in model.calls[0].tools}
    for tool_name in ("historical_weather", "public_holidays"):
        schema = catalog[tool_name].input_schema
        assert set(schema["properties"]) == {"year", "month"}
        assert schema["additionalProperties"] is False
        assert all(
            forbidden not in schema["properties"]
            for forbidden in (
                "url",
                "user_id",
                "store_id",
                "server_path",
                "latitude",
                "longitude",
                "country_code",
            )
        )
    returned = {
        item.tool_result.name: item.tool_result.evidence
        for item in model.calls[1].items
        if item.tool_result is not None
    }
    assert returned["historical_weather"].external_evidence is True
    assert returned["historical_weather"].source == ["open_meteo_historical"]
    assert returned["historical_weather"].geographic_scope.kind == "coordinates"
    assert returned["public_holidays"].external_evidence is True
    assert returned["public_holidays"].source == ["nager_date_public_holidays"]
    assert returned["public_holidays"].geographic_scope.country_code == "IT"
    assert result.turn.content == "外部证据已返回。"


async def test_external_tools_reject_model_owned_scope_and_transport_fields() -> None:
    model = FakeNativeToolModel(
        turns=[
            {
                "message": {"role": "assistant", "content": "尝试越权查询。"},
                "tool_calls": [
                    {
                        "id": "attack-1",
                        "name": "historical_weather",
                        "arguments": {
                            "year": 2026,
                            "month": 7,
                            "url": "https://attacker.invalid",
                            "user_id": 999,
                            "store_id": 999,
                            "server_path": "C:\\secrets",
                            "latitude": 0,
                            "longitude": 0,
                            "country_code": "US",
                        },
                    }
                ],
                "signal": "continue",
            }
        ]
    )
    service = NativeToolAgentService(
        model=model,
        evidence_collector=object(),
        external_evidence_collector=ExternalEvidenceService(
            weather_provider=RecordingWeatherProvider(),
            holiday_provider=RecordingHolidayProvider(),
            now=lambda: NOW,
        ),
        scope_resolver=StaticScopeResolver(),
        now=lambda: NOW,
    )

    with pytest.raises(NativeToolAccessDenied, match="not authorized"):
        await service.run(
            _context(),
            ConversationState(),
            [ModelMessage(role="user", content="调查 2026 年 7 月的天气。")],
        )


async def test_external_weather_fact_is_grounded_without_allowing_causal_claims() -> None:
    evidence = await ExternalEvidenceService(
        weather_provider=RecordingWeatherProvider(),
        holiday_provider=UnusedHolidayProvider(),
        now=lambda: NOW,
    ).historical_weather(
        _context(),
        start=date(2026, 7, 1),
        end=date(2026, 7, 31),
    )
    reference = "ev_0123456789abcdef01234567"
    statement = "2026 年 7 月 1 日的历史天气为多云。"
    claim = NativeAnswerClaim.model_validate(
        {
            "statement": statement,
            "status": "verified_fact",
            "evidence_references": [reference],
            "metric": "historical_weather",
            "period": {"start": "2026-07-01", "end": "2026-07-31"},
            "unit": "external_fact",
            "external_fact": "多云",
        }
    )

    assert answer_is_grounded(
        statement,
        [evidence],
        [claim],
        {reference: evidence},
    )
    wrong_date_statement = "2026 年 7 月 2 日的历史天气为多云。"
    assert not answer_is_grounded(
        wrong_date_statement,
        [evidence],
        [
            claim.model_copy(
                update={"statement": wrong_date_statement},
            )
        ],
        {reference: evidence},
    )
    month_level_statement = "2026 年 7 月的历史天气为多云。"
    assert not answer_is_grounded(
        month_level_statement,
        [evidence],
        [claim.model_copy(update={"statement": month_level_statement})],
        {reference: evidence},
    )
    assert not answer_is_grounded(
        "2026 年 7 月 1 日的多云天气导致营业额下降。",
        [evidence],
        [
            claim.model_copy(
                update={
                    "statement": "2026 年 7 月 1 日的多云天气导致营业额下降。",
                    "relationship": "causation",
                }
            )
        ],
        {reference: evidence},
    )


def test_external_tool_context_rejects_out_of_range_backend_coordinates() -> None:
    with pytest.raises(ValueError, match="store_latitude"):
        RuntimeContext.model_validate(
            {
                **_context().model_dump(),
                "store_latitude": 91,
            }
        )
