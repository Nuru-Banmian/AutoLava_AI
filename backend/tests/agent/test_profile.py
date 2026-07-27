from contextlib import asynccontextmanager

import pytest
from pydantic import ValidationError

from app.agent.factory import create_model_adapter
from app.agent.model import (
    FakeModelAdapter,
    OpenAICompatibleModelAdapter,
    ResilientModelAdapter,
)
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
        model_thinking_parameters={"thinking": {"type": "disabled"}},
        model_timeout_seconds=23,
        model_max_output_tokens=1700,
    )

    adapter = create_model_adapter(settings)

    assert isinstance(adapter, ResilientModelAdapter)
    assert isinstance(adapter.primary, OpenAICompatibleModelAdapter)
    assert str(adapter.primary.profile.base_url) == "https://provider.invalid/v1"
    assert adapter.primary.profile.model_id == "configured-model"
    assert adapter.primary.profile.structured_output_method == "function_calling"
    assert adapter.primary.profile.thinking_parameters == {
        "thinking": {"type": "disabled"}
    }
    assert adapter.primary._client.extra_body == {
        "thinking": {"type": "disabled"}
    }
    assert adapter.primary.profile.timeout_seconds == 23
    assert adapter.primary.profile.max_output_tokens == 1700
    assert "test-only-key" not in repr(adapter.primary.profile)


def test_openai_compatible_profile_fails_closed_when_configuration_is_missing() -> None:
    with pytest.raises(ValidationError, match="model_base_url"):
        Settings(_env_file=None, model_adapter="openai_compatible")


def test_model_thinking_parameters_reject_non_json_values() -> None:
    with pytest.raises(ValidationError, match="model_thinking_parameters"):
        Settings(
            _env_file=None,
            model_thinking_parameters={"thinking": {"type": object()}},
        )


def test_agent_service_applies_the_configured_evidence_batch_limit() -> None:
    @asynccontextmanager
    async def unused_session_factory():
        yield None

    service = create_agent_service(
        Settings(_env_file=None, agent_evidence_batch_limit=1),
        unused_session_factory,
    )

    assert service.workflow.max_evidence_batches == 1
