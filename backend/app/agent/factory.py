from app.agent.model import OpenAICompatibleProfile
from app.agent.native import FakeNativeToolModel, NativeToolModel
from app.agent.native_model import (
    OpenAICompatibleNativeToolModel,
    ResilientNativeToolModel,
)
from app.core.config import Settings


def configured_openai_profiles(
    settings: Settings,
) -> tuple[OpenAICompatibleProfile, OpenAICompatibleProfile | None]:
    primary = OpenAICompatibleProfile(
        provider=settings.model_provider,
        base_url=settings.model_base_url,
        model_id=settings.model_id,
        api_key=settings.model_api_key,
        structured_output_method=settings.model_structured_output_method,
        thinking_parameters=settings.model_thinking_parameters,
        timeout_seconds=settings.model_timeout_seconds,
        max_output_tokens=settings.model_max_output_tokens,
        input_cost_per_million=settings.model_input_cost_per_million,
        output_cost_per_million=settings.model_output_cost_per_million,
    )
    fallback = None
    if settings.fallback_model_base_url.strip():
        fallback = OpenAICompatibleProfile(
            provider=settings.fallback_model_provider,
            base_url=settings.fallback_model_base_url,
            model_id=settings.fallback_model_id,
            api_key=settings.fallback_model_api_key,
            structured_output_method=settings.fallback_model_structured_output_method,
            thinking_parameters=settings.fallback_model_thinking_parameters,
            timeout_seconds=settings.model_timeout_seconds,
            max_output_tokens=settings.model_max_output_tokens,
            input_cost_per_million=settings.fallback_model_input_cost_per_million,
            output_cost_per_million=settings.fallback_model_output_cost_per_million,
        )
    return primary, fallback


def create_native_model_adapter(settings: Settings) -> NativeToolModel:
    if settings.model_adapter == "fake":
        return FakeNativeToolModel()
    primary_profile, fallback_profile = configured_openai_profiles(settings)
    fallback = (
        OpenAICompatibleNativeToolModel(fallback_profile) if fallback_profile is not None else None
    )
    return ResilientNativeToolModel(
        OpenAICompatibleNativeToolModel(primary_profile),
        fallback=fallback,
        retry_attempts=settings.agent_investigation_retry_attempts,
    )
