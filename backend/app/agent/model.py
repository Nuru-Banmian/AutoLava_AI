from collections.abc import Iterable, Sequence
from typing import Any, Literal, Protocol

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, HttpUrl, SecretStr, ValidationError

from app.agent.contracts import EvidenceBundle, ModelMessage, TurnPlan


class ModelAdapterError(RuntimeError):
    """A provider-neutral model failure safe for orchestration decisions."""


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
        )

    async def plan_turn(self, messages: Sequence[ModelMessage]) -> TurnPlan:
        try:
            result = await self._planner.ainvoke(_to_langchain_messages(messages))
            return result if isinstance(result, TurnPlan) else TurnPlan.model_validate(result)
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
            raise ModelAdapterError("invalid structured model output") from None

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
