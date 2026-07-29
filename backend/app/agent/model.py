from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal

from langchain_core.messages import AIMessage
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, JsonValue, SecretStr, ValidationError


class ModelErrorCategory(StrEnum):
    NETWORK = "network"
    TIMEOUT = "timeout"
    RATE_LIMIT = "rate_limit"
    PROVIDER_5XX = "provider_5xx"
    INVALID_API_KEY = "invalid_api_key"
    INSUFFICIENT_BALANCE = "insufficient_balance"
    INVALID_REQUEST = "invalid_request"
    SAFETY_REFUSAL = "safety_refusal"
    PERMISSION_DENIED = "permission_denied"
    INSUFFICIENT_USER_INFO = "insufficient_user_info"
    PROMPT_INJECTION = "prompt_injection"
    INVALID_OUTPUT = "invalid_output"
    UNKNOWN = "unknown"


RECOVERABLE_CATEGORIES = frozenset(
    {
        ModelErrorCategory.NETWORK,
        ModelErrorCategory.TIMEOUT,
        ModelErrorCategory.RATE_LIMIT,
        ModelErrorCategory.PROVIDER_5XX,
    }
)
CONFIGURATION_CATEGORIES = frozenset(
    {
        ModelErrorCategory.INVALID_API_KEY,
        ModelErrorCategory.INSUFFICIENT_BALANCE,
        ModelErrorCategory.INVALID_REQUEST,
    }
)


class ModelAdapterError(RuntimeError):
    """A classified provider-neutral failure; its message is never user-facing."""

    def __init__(
        self,
        message: str,
        *,
        category: ModelErrorCategory = ModelErrorCategory.UNKNOWN,
    ) -> None:
        super().__init__(message)
        self.category = category


@dataclass(frozen=True)
class ModelAttempt:
    stage: Literal["plan", "answer"]
    provider: str
    model: str
    result: Literal["success", "failure"]
    error_category: ModelErrorCategory | None
    latency_ms: int
    input_tokens: int | None = None
    output_tokens: int | None = None
    estimated_cost: float | None = None
    is_fallback: bool = False


AttemptObserver = Callable[[ModelAttempt], None]


class OpenAICompatibleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: str = Field(default="openai_compatible", min_length=1, max_length=60)
    base_url: HttpUrl
    model_id: str = Field(min_length=1)
    api_key: SecretStr
    structured_output_method: Literal["json_schema", "function_calling", "json_mode"] = (
        "json_schema"
    )
    thinking_parameters: dict[str, JsonValue] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30, gt=0, le=120)
    max_output_tokens: int = Field(default=2000, ge=100, le=10_000)
    input_cost_per_million: float | None = Field(default=None, ge=0)
    output_cost_per_million: float | None = Field(default=None, ge=0)


def classify_model_error(error: Exception) -> ModelAdapterError:
    if isinstance(error, ModelAdapterError):
        return error
    status = getattr(error, "status_code", None)
    response = getattr(error, "response", None)
    status = status or getattr(response, "status_code", None)
    name = type(error).__name__.lower()
    text = str(error).lower()
    if "timeout" in name or "timed out" in text:
        category = ModelErrorCategory.TIMEOUT
    elif any(marker in name for marker in ("connection", "network")):
        category = ModelErrorCategory.NETWORK
    elif any(
        marker in text for marker in ("insufficient_quota", "insufficient balance", "billing")
    ):
        category = ModelErrorCategory.INSUFFICIENT_BALANCE
    elif status == 429 or "rate limit" in text:
        category = ModelErrorCategory.RATE_LIMIT
    elif isinstance(status, int) and status >= 500:
        category = ModelErrorCategory.PROVIDER_5XX
    elif status == 401 or any(
        marker in text for marker in ("invalid api key", "incorrect api key")
    ):
        category = ModelErrorCategory.INVALID_API_KEY
    elif status == 403:
        category = ModelErrorCategory.PERMISSION_DENIED
    elif any(marker in text for marker in ("content policy", "safety", "moderation")):
        category = ModelErrorCategory.SAFETY_REFUSAL
    elif status in (400, 404, 422) or isinstance(error, (TypeError, ValueError, ValidationError)):
        category = ModelErrorCategory.INVALID_REQUEST
    else:
        category = ModelErrorCategory.UNKNOWN
    return ModelAdapterError("provider request failed", category=category)


def model_usage(message: AIMessage | None) -> tuple[int | None, int | None]:
    metadata = getattr(message, "usage_metadata", None) or {}
    return metadata.get("input_tokens"), metadata.get("output_tokens")


def estimated_model_cost(
    profile: OpenAICompatibleProfile,
    input_tokens: int | None,
    output_tokens: int | None,
) -> float | None:
    if profile.input_cost_per_million is None and profile.output_cost_per_million is None:
        return None
    return (
        (input_tokens or 0) * (profile.input_cost_per_million or 0)
        + (output_tokens or 0) * (profile.output_cost_per_million or 0)
    ) / 1_000_000
