from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

from app.agent.factory import create_model_adapter
from app.agent.model import (
    FakeModelAdapter,
    OpenAICompatibleModelAdapter,
    ResilientModelAdapter,
)
from app.agent.native import FakeNativeToolModel, NativeToolAgentService
from app.agent.service import create_agent_service
from app.core.config import Settings


def test_ci_profile_constructs_a_fake_adapter_without_provider_configuration() -> None:
    settings = Settings(_env_file=None, model_adapter="fake")

    assert isinstance(create_model_adapter(settings), FakeModelAdapter)


def test_openai_compatible_profile_is_entirely_configuration_driven() -> None:
    settings = Settings(
        _env_file=None,
        model_adapter="openai_compatible",
        model_base_url="https://provider.invalid/v1",
        model_id="configured-model",
        model_api_key="test-only-key",
        model_structured_output_method="function_calling",
        model_timeout_seconds=23,
        model_max_output_tokens=1700,
    )

    adapter = create_model_adapter(settings)

    assert isinstance(adapter, ResilientModelAdapter)
    assert isinstance(adapter.primary, OpenAICompatibleModelAdapter)
    assert str(adapter.primary.profile.base_url) == "https://provider.invalid/v1"
    assert adapter.primary.profile.model_id == "configured-model"
    assert adapter.primary.profile.structured_output_method == "function_calling"
    assert adapter.primary.profile.timeout_seconds == 23
    assert adapter.primary.profile.max_output_tokens == 1700
    assert "test-only-key" not in repr(adapter.primary.profile)


def test_openai_compatible_profile_fails_closed_when_configuration_is_missing() -> None:
    with pytest.raises(ValidationError, match="model_base_url"):
        Settings(_env_file=None, model_adapter="openai_compatible")


def test_agent_service_applies_the_configured_evidence_batch_limit() -> None:
    @asynccontextmanager
    async def unused_session_factory():
        yield None

    service = create_agent_service(
        Settings(_env_file=None, agent_evidence_batch_limit=1),
        unused_session_factory,
    )

    assert service.workflow.max_evidence_batches == 1


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
