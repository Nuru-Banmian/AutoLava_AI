"""Bailian OpenAI-compatible streaming transport; errors never expose response bodies."""

from collections.abc import AsyncIterator
from dataclasses import dataclass
import json

import httpx

from app.core.config import Settings


class ModelFailure(Exception):
    def __init__(self, code: str, *, retryable: bool = False):
        super().__init__(code)
        self.code = code
        self.retryable = retryable


@dataclass(frozen=True)
class ModelUsage:
    tokens: dict[str, int]


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    arguments: str

    def wire(self):
        return {"id": self.id, "type": "function", "function": {
            "name": self.name, "arguments": self.arguments,
        }}


class BailianChat:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model_name = settings.agent_chat_model

    def stream(self, messages):
        return self.stream_tools(messages, [])

    def stream_plan(self, messages, schemas):
        return self.stream_tools(messages, schemas)

    async def stream_tools(self, messages: list[dict], tools: list[dict]) -> AsyncIterator[str | ModelUsage | ToolCall]:
        settings = self.settings
        if not (self.model_name and settings.agent_chat_base_url and
                settings.agent_chat_api_key.get_secret_value()):
            raise ModelFailure("model_not_configured")
        url = settings.agent_chat_base_url.rstrip("/") + "/chat/completions"
        if not url.startswith("https://"):
            raise ModelFailure("model_configuration")
        try:
            async with httpx.AsyncClient(timeout=settings.agent_timeout_seconds) as client:
                async with client.stream("POST", url, headers={
                    "Authorization": f"Bearer {settings.agent_chat_api_key.get_secret_value()}",
                }, json={
                    "model": self.model_name, "messages": messages, "stream": True,
                    "stream_options": {"include_usage": True},
                    "max_tokens": settings.agent_output_tokens,
                    **({"enable_thinking": settings.agent_chat_enable_thinking}
                       if settings.agent_chat_enable_thinking is not None else {}),
                    **({"tools": tools, "parallel_tool_calls": False} if tools else {}),
                }) as response:
                    if response.status_code == 429:
                        raise ModelFailure("model_rate_limited", retryable=True)
                    if response.status_code >= 500:
                        raise ModelFailure("model_unavailable", retryable=True)
                    if response.status_code != 200:
                        raise ModelFailure("model_configuration")
                    finished = False
                    calls = {}
                    buffer = ""
                    # Bound malformed lines as well as generated content.
                    async for chunk in response.aiter_text():
                        buffer += chunk
                        while "\n" in buffer:
                            line, buffer = buffer.split("\n", 1)
                            if len(line) > 65536:
                                raise ModelFailure("model_format")
                            if not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                if not finished:
                                    raise ModelFailure("model_format")
                                for index in sorted(calls):
                                    call = calls[index]
                                    if not call["id"] or not call["name"] or not call["arguments"]:
                                        raise ModelFailure("model_format")
                                    yield ToolCall(**call)
                                return
                            parsed = json.loads(data)
                            if not isinstance(parsed, dict) or "error" in parsed:
                                raise ModelFailure("model_format")
                            usage = parsed.get("usage")
                            if isinstance(usage, dict):
                                yield ModelUsage({key: value for key, value in usage.items()
                                                  if key in ("prompt_tokens", "completion_tokens", "total_tokens")
                                                  and type(value) is int and value >= 0})
                            choices = parsed.get("choices")
                            if not isinstance(choices, list):
                                raise ModelFailure("model_format")
                            for choice in choices:
                                if finished:
                                    raise ModelFailure("model_format")
                                delta = choice.get("delta", {})
                                if not isinstance(delta, dict):
                                    raise ModelFailure("model_format")
                                fragments = delta.get("tool_calls")
                                if fragments is not None:
                                    if not tools or not isinstance(fragments, list):
                                        raise ModelFailure("model_format")
                                    for fragment in fragments:
                                        index = fragment.get("index")
                                        if type(index) is not int or not 0 <= index < settings.agent_max_tool_calls:
                                            raise ModelFailure("model_format")
                                        call = calls.setdefault(index, {"id": "", "name": "", "arguments": ""})
                                        function = fragment.get("function", {})
                                        for key, value in (("id", fragment.get("id", "")),
                                                           ("name", function.get("name", "")),
                                                           ("arguments", function.get("arguments", ""))):
                                            if not isinstance(value, str):
                                                raise ModelFailure("model_format")
                                            call[key] += value
                                        if len(call["id"]) > 160 or len(call["name"]) > 80 or len(call["arguments"]) > 4096:
                                            raise ModelFailure("model_format")
                                content = delta.get("content")
                                if content is not None:
                                    if not isinstance(content, str):
                                        raise ModelFailure("model_format")
                                    if content:
                                        yield content
                                reason = choice.get("finish_reason")
                                if reason == "length":
                                    raise ModelFailure("output_budget")
                                if reason is not None:
                                    if reason not in {"stop", "tool_calls"} or (reason == "tool_calls") != bool(calls):
                                        raise ModelFailure("model_format")
                                    finished = True
                        if len(buffer) > 65536:
                            raise ModelFailure("model_format")
                    # Missing terminator is a truncated response, never success.
                    raise ModelFailure("model_format")
        except httpx.TimeoutException as exc:
            raise ModelFailure("model_timeout", retryable=True) from exc
        except httpx.HTTPError as exc:
            raise ModelFailure("model_unavailable", retryable=True) from exc
        except (ValueError, TypeError, AttributeError) as exc:
            raise ModelFailure("model_format") from exc
