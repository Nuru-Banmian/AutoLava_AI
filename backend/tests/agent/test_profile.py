import pytest
from pydantic import ValidationError

from app.agent.factory import create_model_adapter
from app.agent.model import FakeModelAdapter, OpenAICompatibleModelAdapter
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
    )

    adapter = create_model_adapter(settings)

    assert isinstance(adapter, OpenAICompatibleModelAdapter)
    assert str(adapter.profile.base_url) == "https://provider.invalid/v1"
    assert adapter.profile.model_id == "configured-model"
    assert adapter.profile.structured_output_method == "function_calling"
    assert "test-only-key" not in repr(adapter.profile)


def test_openai_compatible_profile_fails_closed_when_configuration_is_missing() -> None:
    with pytest.raises(ValidationError, match="model_base_url"):
        Settings(_env_file=None, model_adapter="openai_compatible")
