from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
import json
from typing import Any, Protocol

import httpx

from app.core.config import Settings

ModelMessage = dict[str, Any]
ModelTool = dict[str, Any]


@dataclass(frozen=True)
class ModelToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass(frozen=True)
class ModelResponse:
    content: str | None = None
    tool_calls: tuple[ModelToolCall, ...] = ()


class AgentModelAdapter(Protocol):
    async def complete(self, messages: Sequence[ModelMessage]) -> str: ...

    async def respond(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ModelTool],
    ) -> ModelResponse: ...

    def respond_stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ModelTool],
    ) -> AsyncIterator[ModelResponse]: ...

    def stream(
        self,
        messages: Sequence[ModelMessage],
    ) -> AsyncIterator[str]: ...


class BailianOpenAIModelAdapter:
    def __init__(self, settings: Settings) -> None:
        self._endpoint = settings.agent_model_endpoint.rstrip("/")
        self._region = settings.agent_model_region
        self._model_id = settings.agent_model_id
        self._api_key = settings.agent_model_api_key.get_secret_value()

    @property
    def _chat_endpoint(self) -> str:
        if self._endpoint.endswith("/chat/completions"):
            return self._endpoint
        return f"{self._endpoint}/chat/completions"

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "X-DashScope-Region": self._region,
        }

    def _payload(
        self,
        messages: Sequence[ModelMessage],
        *,
        tools: Sequence[ModelTool] | None = None,
        stream: bool = False,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self._model_id,
            "messages": list(messages),
        }
        if tools is not None:
            payload["tools"] = list(tools)
            payload["tool_choice"] = "auto"
        if stream:
            payload["stream"] = True
        return payload

    async def _stream_deltas(
        self,
        messages: Sequence[ModelMessage],
        *,
        tools: Sequence[ModelTool] | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                self._chat_endpoint,
                headers=self._headers,
                json=self._payload(messages, tools=tools, stream=True),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0]["delta"]
                    except (
                        json.JSONDecodeError,
                        KeyError,
                        IndexError,
                        TypeError,
                    ) as exc:
                        raise ValueError(
                            "百炼模型返回了无效流式回答"
                        ) from exc
                    if not isinstance(delta, dict):
                        raise ValueError("百炼模型返回了无效流式回答")
                    yield delta

    async def complete(self, messages: Sequence[ModelMessage]) -> str:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self._chat_endpoint,
                headers=self._headers,
                json=self._payload(messages),
            )
            response.raise_for_status()
        payload = response.json()
        try:
            content = payload["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("百炼模型返回了无效回答") from exc
        if not isinstance(content, str) or not content.strip():
            raise ValueError("百炼模型返回了空回答")
        return content.strip()

    async def respond(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ModelTool],
    ) -> ModelResponse:
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                self._chat_endpoint,
                headers=self._headers,
                json=self._payload(messages, tools=tools),
            )
            response.raise_for_status()
        payload = response.json()
        try:
            message = payload["choices"][0]["message"]
        except (KeyError, IndexError, TypeError) as exc:
            raise ValueError("百炼模型返回了无效回答") from exc
        content = message.get("content")
        if content is not None and not isinstance(content, str):
            raise ValueError("百炼模型返回了无效回答")
        calls: list[ModelToolCall] = []
        for item in message.get("tool_calls") or ():
            try:
                arguments = json.loads(item["function"]["arguments"])
                call = ModelToolCall(
                    id=item["id"],
                    name=item["function"]["name"],
                    arguments=arguments,
                )
            except (KeyError, TypeError, json.JSONDecodeError) as exc:
                raise ValueError("百炼模型返回了无效工具调用") from exc
            if not isinstance(arguments, dict):
                raise ValueError("百炼模型返回了无效工具调用")
            calls.append(call)
        normalized_content = content.strip() if isinstance(content, str) else None
        if not normalized_content and not calls:
            raise ValueError("百炼模型返回了空回答")
        return ModelResponse(
            content=normalized_content or None,
            tool_calls=tuple(calls),
        )

    async def respond_stream(
        self,
        messages: Sequence[ModelMessage],
        tools: Sequence[ModelTool],
    ) -> AsyncIterator[ModelResponse]:
        received_content = False
        tool_fragments: dict[int, dict[str, str]] = {}
        async for delta in self._stream_deltas(messages, tools=tools):
            content = delta.get("content")
            if isinstance(content, str) and content:
                if tool_fragments:
                    raise ValueError("百炼模型混合返回了回答和工具调用")
                received_content = True
                yield ModelResponse(content=content)
            for item in delta.get("tool_calls") or ():
                if received_content:
                    raise ValueError("百炼模型混合返回了回答和工具调用")
                try:
                    index = int(item["index"])
                    fragment = tool_fragments.setdefault(
                        index,
                        {"id": "", "name": "", "arguments": ""},
                    )
                    fragment["id"] += str(item.get("id") or "")
                    function = item.get("function") or {}
                    fragment["name"] += str(function.get("name") or "")
                    fragment["arguments"] += str(
                        function.get("arguments") or ""
                    )
                except (KeyError, TypeError, ValueError) as exc:
                    raise ValueError(
                        "百炼模型返回了无效流式工具调用"
                    ) from exc
        if tool_fragments:
            calls: list[ModelToolCall] = []
            for index in sorted(tool_fragments):
                fragment = tool_fragments[index]
                try:
                    arguments = json.loads(fragment["arguments"])
                except (TypeError, json.JSONDecodeError) as exc:
                    raise ValueError(
                        "百炼模型返回了无效流式工具调用"
                    ) from exc
                if (
                    not fragment["id"]
                    or not fragment["name"]
                    or not isinstance(arguments, dict)
                ):
                    raise ValueError("百炼模型返回了无效流式工具调用")
                calls.append(
                    ModelToolCall(
                        id=fragment["id"],
                        name=fragment["name"],
                        arguments=arguments,
                    )
                )
            yield ModelResponse(tool_calls=tuple(calls))
        elif not received_content:
            raise ValueError("百炼模型返回了空回答")

    async def stream(
        self,
        messages: Sequence[ModelMessage],
    ) -> AsyncIterator[str]:
        received_content = False
        async for delta in self._stream_deltas(messages):
            chunk = delta.get("content")
            if isinstance(chunk, str) and chunk:
                received_content = True
                yield chunk
        if not received_content:
            raise ValueError("百炼模型返回了空回答")
