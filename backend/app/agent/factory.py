from app.agent.model import (
    FakeModelAdapter,
    ModelAdapter,
    OpenAICompatibleModelAdapter,
    OpenAICompatibleProfile,
)
from app.core.config import Settings


def create_model_adapter(settings: Settings) -> ModelAdapter:
    if settings.model_adapter == "fake":
        return FakeModelAdapter()
    profile = OpenAICompatibleProfile(
        base_url=settings.model_base_url,
        model_id=settings.model_id,
        api_key=settings.model_api_key,
        structured_output_method=settings.model_structured_output_method,
    )
    return OpenAICompatibleModelAdapter(profile)
