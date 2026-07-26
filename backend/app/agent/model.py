from collections.abc import Iterable, Sequence
import json
from typing import Any, Literal, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, ValidationError

from app.agent.contracts import EvidenceBundle, ModelMessage, TurnPlan


class ModelAdapterError(RuntimeError):
    """A provider-neutral model failure safe for orchestration decisions."""


class RepairableModelPlanError(ModelAdapterError):
    """A format, enum, or structural model-plan error eligible for one repair."""


class UnsafeModelPlanError(ModelAdapterError):
    """A model-plan error involving server-owned scope or query capabilities."""


class ModelAdapter(Protocol):
    async def plan_turn(self, messages: Sequence[ModelMessage]) -> TurnPlan: ...

    async def answer_turn(
        self,
        messages: Sequence[ModelMessage],
        evidence: EvidenceBundle,
    ) -> str: ...


class OpenAICompatibleProfile(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    base_url: HttpUrl
    model_id: str = Field(min_length=1)
    api_key: SecretStr
    structured_output_method: Literal["json_schema", "function_calling", "json_mode"] = (
        "json_schema"
    )
    max_retries: Literal[0, 1] = 1


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
            max_retries=profile.max_retries,
        )
        self._planner = self._client.with_structured_output(
            TurnPlan,
            method=profile.structured_output_method,
            include_raw=True,
        )

    async def plan_turn(self, messages: Sequence[ModelMessage]) -> TurnPlan:
        try:
            result = await self._planner.ainvoke(_to_langchain_messages(messages))
            if isinstance(result, TurnPlan):
                return result
            if isinstance(result, dict) and {"parsed", "parsing_error"} <= result.keys():
                parsed = result["parsed"]
                if isinstance(parsed, TurnPlan):
                    return parsed
                if parsed is not None:
                    try:
                        return TurnPlan.model_validate(parsed)
                    except ValidationError:
                        raise _plan_validation_error(parsed) from None
                raise _plan_validation_error(_raw_model_payload(result.get("raw")))
            try:
                return TurnPlan.model_validate(result)
            except ValidationError:
                raise _plan_validation_error(result) from None
        except (RepairableModelPlanError, UnsafeModelPlanError):
            raise
        except ValidationError:
            raise RepairableModelPlanError("invalid structured model output") from None
        except Exception as error:
            raise ModelAdapterError("model planning failed") from error

    async def answer_turn(
        self,
        messages: Sequence[ModelMessage],
        evidence: EvidenceBundle,
    ) -> str:
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
            return content
        except Exception as error:
            raise ModelAdapterError("model answer failed") from error


ScriptedPlan = TurnPlan | dict[str, Any] | Exception
ScriptedAnswer = str | Exception


class FakeModelAdapter:
    """Deterministic CI adapter; it never constructs a network client."""

    def __init__(
        self,
        *,
        plans: Iterable[ScriptedPlan] = (),
        answers: Iterable[ScriptedAnswer] = (),
    ) -> None:
        self._plans = list(plans)
        self._answers = list(answers)
        self.plan_calls = 0
        self.answer_calls = 0

    @property
    def total_calls(self) -> int:
        return self.plan_calls + self.answer_calls

    async def plan_turn(self, messages: Sequence[ModelMessage]) -> TurnPlan:
        del messages
        self.plan_calls += 1
        scripted = _pop_scripted(self._plans)
        if isinstance(scripted, Exception):
            raise scripted
        try:
            return scripted if isinstance(scripted, TurnPlan) else TurnPlan.model_validate(scripted)
        except ValidationError:
            raise _plan_validation_error(scripted) from None

    async def answer_turn(
        self,
        messages: Sequence[ModelMessage],
        evidence: EvidenceBundle,
    ) -> str:
        del messages, evidence
        self.answer_calls += 1
        scripted = _pop_scripted(self._answers)
        if isinstance(scripted, Exception):
            raise scripted
        if not isinstance(scripted, str) or not scripted.strip():
            raise ModelAdapterError("invalid model answer")
        return scripted


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
    "store_id",
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
