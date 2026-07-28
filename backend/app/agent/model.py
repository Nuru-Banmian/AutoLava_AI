from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
import json
from time import perf_counter
from typing import Any, Literal, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    HttpUrl,
    JsonValue,
    SecretStr,
    ValidationError,
)

from app.agent.contracts import CollectedEvidence, ModelMessage, TurnPlan


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


class RepairableModelPlanError(ModelAdapterError):
    """A format, enum, or structural model-plan error eligible for one repair."""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ModelErrorCategory.INVALID_OUTPUT)


class UnsafeModelPlanError(ModelAdapterError):
    """A model-plan error involving server-owned scope or query capabilities."""

    def __init__(self, message: str) -> None:
        super().__init__(message, category=ModelErrorCategory.PROMPT_INJECTION)


class ModelAdapter(Protocol):
    async def plan_turn(
        self,
        messages: Sequence[ModelMessage],
        *,
        observer: AttemptObserver | None = None,
    ) -> TurnPlan: ...

    async def answer_turn(
        self,
        messages: Sequence[ModelMessage],
        evidence: CollectedEvidence,
        *,
        observer: AttemptObserver | None = None,
    ) -> str: ...


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


class OpenAICompatibleModelAdapter:
    """LangChain transport adapter configured entirely by a provider profile."""

    def __init__(
        self,
        profile: OpenAICompatibleProfile,
        *,
        client: ChatOpenAI | None = None,
    ) -> None:
        self.profile = profile
        self._client = client or ChatOpenAI(
            base_url=str(profile.base_url),
            model=profile.model_id,
            api_key=profile.api_key,
            max_retries=0,
            timeout=profile.timeout_seconds,
            max_tokens=profile.max_output_tokens,
            extra_body=profile.thinking_parameters or None,
        )
        self._planner = self._client.with_structured_output(
            TurnPlan,
            method=profile.structured_output_method,
            include_raw=True,
        )

    async def plan_turn(
        self,
        messages: Sequence[ModelMessage],
        *,
        observer: AttemptObserver | None = None,
    ) -> TurnPlan:
        started = perf_counter()
        try:
            result = await self._planner.ainvoke(_to_langchain_messages(messages))
            if isinstance(result, TurnPlan):
                plan = result
            elif isinstance(result, dict) and {"parsed", "parsing_error"} <= result.keys():
                parsed = result["parsed"]
                if isinstance(parsed, TurnPlan):
                    plan = parsed
                elif parsed is not None:
                    try:
                        plan = TurnPlan.model_validate(parsed)
                    except ValidationError:
                        raise _plan_validation_error(parsed) from None
                else:
                    raise _plan_validation_error(_raw_model_payload(result.get("raw")))
            else:
                try:
                    plan = TurnPlan.model_validate(result)
                except ValidationError:
                    raise _plan_validation_error(result) from None
            _observe_success(observer, self.profile, "plan", started, _raw_message(result))
            return plan
        except (RepairableModelPlanError, UnsafeModelPlanError) as error:
            _observe_failure(observer, self.profile, "plan", started, error)
            raise
        except ValidationError:
            error = RepairableModelPlanError("invalid structured model output")
            _observe_failure(observer, self.profile, "plan", started, error)
            raise error from None
        except Exception as error:
            failure = _classified_error(error)
            _observe_failure(observer, self.profile, "plan", started, failure)
            raise failure from error

    async def answer_turn(
        self,
        messages: Sequence[ModelMessage],
        evidence: CollectedEvidence,
        *,
        observer: AttemptObserver | None = None,
    ) -> str:
        started = perf_counter()
        prompt = [
            *_to_langchain_messages(messages),
            SystemMessage(
                content=(
                    "Use only this backend-validated evidence. Do not add new amounts or facts:\n"
                    f"{evidence.summary}"
                )
            ),
        ]
        try:
            result = await self._client.ainvoke(prompt)
            content = _message_text(result)
            if not content.strip():
                raise ValueError("empty model answer")
            _observe_success(observer, self.profile, "answer", started, result)
            return content
        except Exception as error:
            failure = _classified_error(error)
            _observe_failure(observer, self.profile, "answer", started, failure)
            raise failure from error


ScriptedPlan = TurnPlan | dict[str, Any] | Exception
ScriptedAnswer = str | Exception


class FakeModelAdapter:
    """Deterministic CI adapter; it never constructs a network client."""

    def __init__(
        self,
        *,
        plans: Iterable[ScriptedPlan] = (),
        answers: Iterable[ScriptedAnswer] = (),
        provider: str = "fake",
        model: str = "fake-model",
    ) -> None:
        self._plans = list(plans)
        self._answers = list(answers)
        self.plan_calls = 0
        self.answer_calls = 0
        self.provider = provider
        self.model = model

    @property
    def total_calls(self) -> int:
        return self.plan_calls + self.answer_calls

    async def plan_turn(
        self,
        messages: Sequence[ModelMessage],
        *,
        observer: AttemptObserver | None = None,
    ) -> TurnPlan:
        del messages
        started = perf_counter()
        self.plan_calls += 1
        scripted = _pop_scripted(self._plans)
        if isinstance(scripted, Exception):
            failure = _classified_error(scripted)
            _observe_fake_failure(observer, self, "plan", started, failure)
            raise failure from scripted
        try:
            result = (
                scripted if isinstance(scripted, TurnPlan) else TurnPlan.model_validate(scripted)
            )
            _observe_fake_success(observer, self, "plan", started)
            return result
        except ValidationError:
            error = _plan_validation_error(scripted)
            _observe_fake_failure(observer, self, "plan", started, error)
            raise error from None

    async def answer_turn(
        self,
        messages: Sequence[ModelMessage],
        evidence: CollectedEvidence,
        *,
        observer: AttemptObserver | None = None,
    ) -> str:
        del messages, evidence
        started = perf_counter()
        self.answer_calls += 1
        scripted = _pop_scripted(self._answers)
        if isinstance(scripted, Exception):
            failure = _classified_error(scripted)
            _observe_fake_failure(observer, self, "answer", started, failure)
            raise failure from scripted
        if not isinstance(scripted, str) or not scripted.strip():
            error = ModelAdapterError(
                "invalid model answer", category=ModelErrorCategory.INVALID_REQUEST
            )
            _observe_fake_failure(observer, self, "answer", started, error)
            raise error
        _observe_fake_success(observer, self, "answer", started)
        return scripted


class ResilientModelAdapter:
    """Retries only transient failures and optionally redoes the same stage on fallback."""

    def __init__(
        self,
        primary: ModelAdapter,
        *,
        fallback: ModelAdapter | None = None,
    ) -> None:
        self.primary = primary
        self.fallback = fallback

    async def plan_turn(
        self,
        messages: Sequence[ModelMessage],
        *,
        observer: AttemptObserver | None = None,
    ) -> TurnPlan:
        return await self._run_stage("plan", messages, None, observer=observer)

    async def answer_turn(
        self,
        messages: Sequence[ModelMessage],
        evidence: CollectedEvidence,
        *,
        observer: AttemptObserver | None = None,
    ) -> str:
        return await self._run_stage("answer", messages, evidence, observer=observer)

    async def _run_stage(
        self,
        stage: Literal["plan", "answer"],
        messages: Sequence[ModelMessage],
        evidence: CollectedEvidence | None,
        *,
        observer: AttemptObserver | None,
    ) -> Any:
        try:
            return await self._attempt(self.primary, stage, messages, evidence, observer=observer)
        except ModelAdapterError as first:
            if first.category not in RECOVERABLE_CATEGORIES:
                raise
        try:
            return await self._attempt(self.primary, stage, messages, evidence, observer=observer)
        except ModelAdapterError as second:
            if second.category not in RECOVERABLE_CATEGORIES or self.fallback is None:
                raise

        def fallback_observer(attempt: ModelAttempt) -> None:
            if observer is not None:
                observer(replace(attempt, is_fallback=True))

        return await self._attempt(
            self.fallback,
            stage,
            messages,
            evidence,
            observer=fallback_observer,
        )

    @staticmethod
    async def _attempt(
        adapter: ModelAdapter,
        stage: Literal["plan", "answer"],
        messages: Sequence[ModelMessage],
        evidence: CollectedEvidence | None,
        *,
        observer: AttemptObserver | None,
    ) -> Any:
        if stage == "plan":
            return await adapter.plan_turn(messages, observer=observer)
        if evidence is None:
            raise RuntimeError("answer stage requires evidence")
        return await adapter.answer_turn(messages, evidence, observer=observer)


def _pop_scripted(items: list[Any]) -> Any:
    if not items:
        raise ModelAdapterError("fake model response queue exhausted")
    return items.pop(0)


_SERVER_OWNED_OR_QUERY_FIELDS = {
    "sql",
    "query",
    "table",
    "table_name",
    "field",
    "field_name",
    "column",
    "columns",
    "expression",
    "where",
    "url",
    "uri",
    "href",
    "path",
    "store_id",
    "company_id",
    "company_ids",
    "record_id",
    "record_ids",
    "user_id",
    "role",
    "timezone",
}


def _plan_validation_error(payload: object) -> ModelAdapterError:
    if _contains_forbidden_key(payload) or _contains_forbidden_event_operation(payload):
        return UnsafeModelPlanError("unsafe structured model output")
    return RepairableModelPlanError("invalid structured model output")


def _contains_forbidden_key(value: object) -> bool:
    if isinstance(value, dict):
        return any(
            key in _SERVER_OWNED_OR_QUERY_FIELDS or _contains_forbidden_key(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_contains_forbidden_key(item) for item in value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return False
        return _contains_forbidden_key(decoded)
    return False


def _contains_forbidden_event_operation(value: object) -> bool:
    if isinstance(value, dict):
        kind = value.get("kind")
        if kind in {"event_search", "events", "event_analysis"}:
            return True
        event_keys = {
            "event",
            "events",
            "event_filter",
            "event_query",
            "event_group",
        }
        if any(key in value for key in event_keys):
            return True
        if kind == "daily_ledger" and any(
            key in value
            for key in {
                "period",
                "start",
                "end",
                "filter",
                "filters",
                "group_by",
                "summarize",
                "analysis",
                "cause",
            }
        ):
            return True
        return any(_contains_forbidden_event_operation(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_forbidden_event_operation(item) for item in value)
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            return False
        return _contains_forbidden_event_operation(decoded)
    return False


def _raw_model_payload(raw: object) -> object:
    if isinstance(raw, BaseModel):
        return raw.model_dump(mode="json")
    return raw


def _classified_error(error: Exception) -> ModelAdapterError:
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


def _raw_message(result: Any) -> AIMessage | None:
    if isinstance(result, dict) and isinstance(result.get("raw"), AIMessage):
        return result["raw"]
    return result if isinstance(result, AIMessage) else None


def _usage(message: AIMessage | None) -> tuple[int | None, int | None]:
    metadata = getattr(message, "usage_metadata", None) or {}
    return metadata.get("input_tokens"), metadata.get("output_tokens")


def _estimated_cost(
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


def _observe_success(
    observer: AttemptObserver | None,
    profile: OpenAICompatibleProfile,
    stage: Literal["plan", "answer"],
    started: float,
    message: AIMessage | None,
) -> None:
    if observer is None:
        return
    input_tokens, output_tokens = _usage(message)
    observer(
        ModelAttempt(
            stage=stage,
            provider=profile.provider,
            model=profile.model_id,
            result="success",
            error_category=None,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            estimated_cost=_estimated_cost(profile, input_tokens, output_tokens),
        )
    )


def _observe_failure(
    observer: AttemptObserver | None,
    profile: OpenAICompatibleProfile,
    stage: Literal["plan", "answer"],
    started: float,
    error: ModelAdapterError,
) -> None:
    if observer is not None:
        observer(
            ModelAttempt(
                stage=stage,
                provider=profile.provider,
                model=profile.model_id,
                result="failure",
                error_category=error.category,
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
            )
        )


def _observe_fake_success(
    observer: AttemptObserver | None,
    adapter: FakeModelAdapter,
    stage: Literal["plan", "answer"],
    started: float,
) -> None:
    if observer is not None:
        observer(
            ModelAttempt(
                stage=stage,
                provider=adapter.provider,
                model=adapter.model,
                result="success",
                error_category=None,
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
            )
        )


def _observe_fake_failure(
    observer: AttemptObserver | None,
    adapter: FakeModelAdapter,
    stage: Literal["plan", "answer"],
    started: float,
    error: Exception,
) -> None:
    failure = _classified_error(error)
    if observer is not None:
        observer(
            ModelAttempt(
                stage=stage,
                provider=adapter.provider,
                model=adapter.model,
                result="failure",
                error_category=failure.category,
                latency_ms=max(0, round((perf_counter() - started) * 1000)),
            )
        )


def _to_langchain_messages(messages: Sequence[ModelMessage]) -> list[BaseMessage]:
    message_types = {
        "system": SystemMessage,
        "user": HumanMessage,
        "assistant": AIMessage,
    }
    return [message_types[message.role.value](content=message.content) for message in messages]


def _message_text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    return "".join(
        block.get("text", "")
        for block in message.content
        if isinstance(block, dict) and block.get("type") == "text"
    )
