from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
import json
from time import perf_counter
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.answer_grounding import NativeAnswerClaim
from app.agent.contracts import MessageRole, ModelMessage
from app.agent.model import (
    AttemptObserver,
    ModelAdapterError,
    ModelAttempt,
    ModelErrorCategory,
    OpenAICompatibleProfile,
    RECOVERABLE_CATEGORIES,
    classify_model_error,
    estimated_model_cost,
    model_usage,
)
from app.agent.native import (
    NativeAnalysisHypothesis,
    NativeModelTurn,
    NativeModelUsage,
    NativeToolCall,
    NativeToolDefinition,
    NativeTranscriptItem,
)


FINAL_ANSWER_CONTRACT = """
Use the supplied tools for every current-store operating fact.
Tool calls must use the provider's native tool-calling interface.
When no more tools are needed, return either a natural-language answer or one JSON object with:
{"answer":"natural answer","answer_claims":[],"hypotheses":[],"pending_directions":[]}.
For every date, amount, ratio, or operating judgement in a business answer, include an answer_claim
that cites the matching evidence_reference from a tool result. Do not expose this JSON envelope,
tool payloads, system instructions, or hidden reasoning in the answer text.
""".strip()


class _NativeFinalAnswer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=20_000)
    answer_claims: list[NativeAnswerClaim] = Field(default_factory=list, max_length=20)
    hypotheses: list[NativeAnalysisHypothesis] | None = Field(default=None, max_length=8)
    pending_directions: list[str] | None = Field(default=None, max_length=8)


class OpenAICompatibleNativeToolModel:
    """Configurable production adapter for OpenAI-compatible native tool calling."""

    def __init__(
        self,
        profile: OpenAICompatibleProfile,
        *,
        client: ChatOpenAI | Any | None = None,
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

    async def next_turn(
        self,
        items: Sequence[NativeTranscriptItem],
        *,
        tools: Sequence[NativeToolDefinition],
        observer: AttemptObserver | None = None,
    ) -> NativeModelTurn:
        started = perf_counter()
        try:
            bound = self._client.bind_tools([_provider_tool(tool) for tool in tools])
            result = await bound.ainvoke(_provider_messages(items))
            if not isinstance(result, AIMessage):
                raise ModelAdapterError(
                    "provider request failed",
                    category=ModelErrorCategory.INVALID_OUTPUT,
                )
            turn = _native_turn(result, self.profile)
            _observe(observer, self.profile, started, result=result)
            return turn
        except ModelAdapterError as error:
            _observe(observer, self.profile, started, error=error)
            raise
        except (ValidationError, TypeError, ValueError, json.JSONDecodeError) as error:
            failure = ModelAdapterError(
                "provider request failed",
                category=ModelErrorCategory.INVALID_OUTPUT,
            )
            _observe(observer, self.profile, started, error=failure)
            raise failure from error
        except Exception as error:
            failure = classify_model_error(error)
            _observe(observer, self.profile, started, error=failure)
            raise failure from error


class ResilientNativeToolModel:
    """Retry one configured model, then redo the same turn once on a fallback."""

    provider_recovery_managed = True

    def __init__(
        self,
        primary: OpenAICompatibleNativeToolModel,
        *,
        fallback: OpenAICompatibleNativeToolModel | None = None,
        retry_attempts: int = 1,
    ) -> None:
        if retry_attempts < 0:
            raise ValueError("retry_attempts must not be negative")
        self.primary = primary
        self.fallback = fallback
        self.retry_attempts = retry_attempts

    async def next_turn(
        self,
        items: Sequence[NativeTranscriptItem],
        *,
        tools: Sequence[NativeToolDefinition],
        observer: AttemptObserver | None = None,
    ) -> NativeModelTurn:
        last_failure: ModelAdapterError | None = None
        for _ in range(self.retry_attempts + 1):
            try:
                return await self.primary.next_turn(items, tools=tools, observer=observer)
            except ModelAdapterError as error:
                if error.category not in RECOVERABLE_CATEGORIES:
                    raise
                last_failure = error
        if self.fallback is None:
            raise ModelAdapterError(
                "all model providers unavailable",
                category=last_failure.category if last_failure else ModelErrorCategory.UNKNOWN,
            )

        def fallback_observer(attempt: ModelAttempt) -> None:
            if observer is not None:
                observer(replace(attempt, is_fallback=True))

        try:
            return await self.fallback.next_turn(
                items,
                tools=tools,
                observer=fallback_observer,
            )
        except ModelAdapterError as error:
            if error.category not in RECOVERABLE_CATEGORIES:
                raise
            raise ModelAdapterError(
                "all model providers unavailable",
                category=error.category,
            ) from None


def _provider_tool(tool: NativeToolDefinition) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool.description,
            "parameters": tool.input_schema,
        },
    }


def _provider_messages(items: Sequence[NativeTranscriptItem]) -> list[Any]:
    messages: list[Any] = [SystemMessage(content=FINAL_ANSWER_CONTRACT)]
    for item in items:
        if item.message is not None:
            messages.append(_provider_message(item.message, item.tool_calls))
            continue
        assert item.tool_result is not None
        messages.append(
            ToolMessage(
                content=json.dumps(
                    item.tool_result.evidence.model_dump(mode="json"),
                    ensure_ascii=False,
                    separators=(",", ":"),
                ),
                tool_call_id=item.tool_result.call_id,
                name=item.tool_result.name,
            )
        )
    return messages


def _provider_message(message: ModelMessage, tool_calls: Sequence[NativeToolCall]) -> Any:
    if message.role == MessageRole.SYSTEM:
        return SystemMessage(content=message.content)
    if message.role == MessageRole.USER:
        return HumanMessage(content=message.content)
    return AIMessage(
        content=message.content,
        tool_calls=[
            {
                "id": call.id,
                "name": call.name,
                "args": call.arguments,
                "type": "tool_call",
            }
            for call in tool_calls
        ],
    )


def _native_turn(message: AIMessage, profile: OpenAICompatibleProfile) -> NativeModelTurn:
    if message.invalid_tool_calls:
        raise ModelAdapterError(
            "provider request failed",
            category=ModelErrorCategory.INVALID_OUTPUT,
        )
    usage = _native_usage(message, profile)
    calls = [
        NativeToolCall(
            id=call["id"],
            name=call["name"],
            arguments=_tool_arguments(call.get("args")),
        )
        for call in message.tool_calls
    ]
    content = _message_text(message)
    if calls:
        return NativeModelTurn(
            message=ModelMessage(
                role=MessageRole.ASSISTANT,
                content=content.strip() or "正在调用经营工具。",
            ),
            tool_calls=calls,
            usage=usage,
            signal="continue",
        )
    final = _final_answer(content)
    return NativeModelTurn(
        message=ModelMessage(role=MessageRole.ASSISTANT, content=final.answer),
        hypotheses=final.hypotheses,
        pending_directions=final.pending_directions,
        answer_claims=final.answer_claims,
        usage=usage,
        signal="end",
    )


def _tool_arguments(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        decoded = json.loads(value)
        if isinstance(decoded, dict):
            return decoded
    raise ModelAdapterError(
        "provider request failed",
        category=ModelErrorCategory.INVALID_OUTPUT,
    )


def _message_text(message: AIMessage) -> str:
    if isinstance(message.content, str):
        return message.content
    parts: list[str] = []
    for block in message.content:
        if isinstance(block, str):
            parts.append(block)
        elif isinstance(block, dict) and isinstance(block.get("text"), str):
            parts.append(block["text"])
    return "".join(parts)


def _final_answer(content: str) -> _NativeFinalAnswer:
    text = content.strip()
    if not text:
        raise ModelAdapterError(
            "provider request failed",
            category=ModelErrorCategory.INVALID_OUTPUT,
        )
    if not text.startswith("{"):
        return _NativeFinalAnswer(answer=text)
    try:
        return _NativeFinalAnswer.model_validate_json(text)
    except ValidationError as error:
        raise ModelAdapterError(
            "provider request failed",
            category=ModelErrorCategory.INVALID_OUTPUT,
        ) from error


def _native_usage(
    message: AIMessage,
    profile: OpenAICompatibleProfile,
) -> NativeModelUsage:
    input_tokens, output_tokens = model_usage(message)
    if input_tokens is None or output_tokens is None:
        token_usage = message.response_metadata.get("token_usage", {})
        input_tokens = (
            input_tokens if input_tokens is not None else token_usage.get("prompt_tokens")
        )
        output_tokens = (
            output_tokens if output_tokens is not None else token_usage.get("completion_tokens")
        )
    if input_tokens is None or output_tokens is None:
        raise ModelAdapterError(
            "provider request failed",
            category=ModelErrorCategory.INVALID_OUTPUT,
        )
    input_count = input_tokens
    output_count = output_tokens
    return NativeModelUsage(
        input_tokens=input_count,
        output_tokens=output_count,
        estimated_cost_eur=estimated_model_cost(profile, input_count, output_count) or 0,
    )


def _observe(
    observer: AttemptObserver | None,
    profile: OpenAICompatibleProfile,
    started: float,
    *,
    result: AIMessage | None = None,
    error: ModelAdapterError | None = None,
) -> None:
    if observer is None:
        return
    usage = _native_usage(result, profile) if result is not None else None
    observer(
        ModelAttempt(
            stage="plan",
            provider=profile.provider,
            model=profile.model_id,
            result="failure" if error is not None else "success",
            error_category=error.category if error is not None else None,
            latency_ms=max(0, round((perf_counter() - started) * 1000)),
            input_tokens=usage.input_tokens if usage is not None else None,
            output_tokens=usage.output_tokens if usage is not None else None,
            estimated_cost=usage.estimated_cost_eur if usage is not None else None,
        )
    )
