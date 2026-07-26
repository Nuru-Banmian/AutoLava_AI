from app.agent.model import (
    FakeModelAdapter,
    ModelAdapter,
    OpenAICompatibleModelAdapter,
    OpenAICompatibleProfile,
    ResilientModelAdapter,
)
from app.core.config import Settings


def create_model_adapter(settings: Settings) -> ModelAdapter:
    if settings.model_adapter == "fake":
        return FakeModelAdapter()
    profile = OpenAICompatibleProfile(
        provider=settings.model_provider,
        base_url=settings.model_base_url,
        model_id=settings.model_id,
        api_key=settings.model_api_key,
        structured_output_method=settings.model_structured_output_method,
        thinking_parameters=settings.model_thinking_parameters,
        input_cost_per_million=settings.model_input_cost_per_million,
        output_cost_per_million=settings.model_output_cost_per_million,
    )
    fallback = None
    if settings.fallback_model_base_url.strip():
        fallback = OpenAICompatibleModelAdapter(
            OpenAICompatibleProfile(
                provider=settings.fallback_model_provider,
                base_url=settings.fallback_model_base_url,
                model_id=settings.fallback_model_id,
                api_key=settings.fallback_model_api_key,
                structured_output_method=settings.fallback_model_structured_output_method,
                thinking_parameters=settings.fallback_model_thinking_parameters,
                input_cost_per_million=settings.fallback_model_input_cost_per_million,
                output_cost_per_million=settings.fallback_model_output_cost_per_million,
            )
        )
    return ResilientModelAdapter(
        OpenAICompatibleModelAdapter(profile),
        fallback=fallback,
    )
