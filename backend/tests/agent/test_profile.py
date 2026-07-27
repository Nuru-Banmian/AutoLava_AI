import pytest
from pydantic import ValidationError

from app.agent.factory import create_model_adapter
from app.agent.model import (
    FakeModelAdapter,
    OpenAICompatibleModelAdapter,
    ResilientModelAdapter,
)
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
