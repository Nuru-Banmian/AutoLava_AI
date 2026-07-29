from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

from app.agent.factory import create_native_model_adapter
from app.agent.native import FakeNativeToolModel, NativeToolAgentService
from app.agent.native_model import (
    OpenAICompatibleNativeToolModel,
    ResilientNativeToolModel,
)
from app.agent.service import create_agent_service
from app.core.config import Settings


def test_ci_profile_constructs_only_the_native_tool_loop_without_provider_configuration() -> None:
    @asynccontextmanager
    async def unused_session_factory():
        yield None

    service = create_agent_service(
        Settings(_env_file=None, model_adapter="fake"),
        unused_session_factory,
    )

    assert isinstance(service, NativeToolAgentService)
    assert isinstance(service.model, FakeNativeToolModel)


def test_openai_compatible_native_profile_is_entirely_configuration_driven() -> None:
    settings = Settings(
        _env_file=None,
        model_adapter="openai_compatible",
        model_provider="candidate",
        model_base_url="https://provider.invalid/v1",
        model_id="configured-model",
        model_api_key="test-only-key",
        model_thinking_parameters={"thinking": {"type": "disabled"}},
        model_timeout_seconds=23,
        model_max_output_tokens=1700,
        model_input_cost_per_million=1,
        model_output_cost_per_million=2,
        fallback_model_provider="backup",
        fallback_model_base_url="https://backup.invalid/v1",
        fallback_model_id="backup-model",
        fallback_model_api_key="test-only-backup-key",
        agent_investigation_retry_attempts=1,
    )

    adapter = create_native_model_adapter(settings)

    assert isinstance(adapter, ResilientNativeToolModel)
    assert isinstance(adapter.primary, OpenAICompatibleNativeToolModel)
    assert str(adapter.primary.profile.base_url) == "https://provider.invalid/v1"
    assert adapter.primary.profile.provider == "candidate"
    assert adapter.primary.profile.model_id == "configured-model"
    assert adapter.primary.profile.thinking_parameters == {"thinking": {"type": "disabled"}}
    assert adapter.primary.profile.timeout_seconds == 23
    assert adapter.primary.profile.max_output_tokens == 1700
    assert adapter.primary.profile.input_cost_per_million == 1
    assert adapter.primary.profile.output_cost_per_million == 2
    assert adapter.retry_attempts == 1
    assert adapter.fallback is not None
    assert adapter.fallback.profile.provider == "backup"
    assert adapter.fallback.profile.model_id == "backup-model"
    assert "test-only-key" not in repr(adapter.primary.profile)
    assert "test-only-backup-key" not in repr(adapter.fallback.profile)


def test_production_agent_service_uses_the_native_tool_loop() -> None:
    @asynccontextmanager
    async def unused_session_factory():
        yield None

    service = create_agent_service(
        Settings(
            _env_file=None,
            model_adapter="openai_compatible",
            model_base_url="https://provider.invalid/v1",
            model_id="configured-model",
            model_api_key="test-only-key",
        ),
        unused_session_factory,
    )

    assert isinstance(service, NativeToolAgentService)
    assert isinstance(service.model, ResilientNativeToolModel)


def test_openai_compatible_profile_fails_closed_when_configuration_is_missing() -> None:
    with pytest.raises(ValidationError, match="model_base_url"):
        Settings(_env_file=None, model_adapter="openai_compatible")


def test_model_thinking_parameters_reject_non_json_values() -> None:
    with pytest.raises(ValidationError, match="model_thinking_parameters"):
        Settings(
            _env_file=None,
            model_thinking_parameters={"thinking": {"type": object()}},
        )


def test_native_investigation_safety_limits_are_configuration_driven() -> None:
    settings = Settings(
        _env_file=None,
        agent_investigation_max_model_calls=5,
        agent_investigation_max_tool_calls=9,
        agent_investigation_timeout_seconds=45,
        agent_investigation_max_tokens=24_000,
        agent_investigation_max_cost_eur=0.35,
        agent_investigation_retry_attempts=2,
    )

    assert settings.agent_investigation_max_model_calls == 5
    assert settings.agent_investigation_max_tool_calls == 9
    assert settings.agent_investigation_timeout_seconds == 45
    assert settings.agent_investigation_max_tokens == 24_000
    assert settings.agent_investigation_max_cost_eur == 0.35
    assert settings.agent_investigation_retry_attempts == 2


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("agent_investigation_max_model_calls", 0),
        ("agent_investigation_max_tool_calls", 0),
        ("agent_investigation_timeout_seconds", 0),
        ("agent_investigation_max_tokens", 0),
        ("agent_investigation_max_cost_eur", 0),
        ("agent_investigation_retry_attempts", -1),
    ],
)
def test_native_investigation_safety_limits_reject_invalid_values(
    field: str,
    value: int,
) -> None:
    with pytest.raises(ValidationError, match=field):
        Settings(_env_file=None, **{field: value})


def test_agent_service_applies_configured_native_investigation_limits() -> None:
    @asynccontextmanager
    async def unused_session_factory():
        yield None

    service = create_agent_service(
        Settings(
            _env_file=None,
            agent_investigation_max_model_calls=5,
            agent_investigation_max_tool_calls=9,
            agent_investigation_timeout_seconds=45,
            agent_investigation_max_tokens=24_000,
            agent_investigation_max_cost_eur=0.35,
            agent_investigation_retry_attempts=2,
        ),
        unused_session_factory,
        native_model=FakeNativeToolModel(turns=[]),
    )

    assert isinstance(service, NativeToolAgentService)
    assert service.limits.model_dump() == {
        "max_model_calls": 5,
        "max_tool_calls": 9,
        "timeout_seconds": 45.0,
        "max_tokens": 24_000,
        "max_cost_eur": 0.35,
        "retry_attempts": 2,
    }
