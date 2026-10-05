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


class BailianChat:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.model_name = settings.agent_chat_model

    async def stream(self, messages: list[dict[str, str]]) -> AsyncIterator[str | ModelUsage]:
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
                }) as response:
                    if response.status_code == 429:
                        raise ModelFailure("model_rate_limited", retryable=True)
                    if response.status_code >= 500:
                        raise ModelFailure("model_unavailable", retryable=True)
                    if response.status_code != 200:
                        raise ModelFailure("model_configuration")
                    finished = False
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
                                delta = choice.get("delta", {})
                                if not isinstance(delta, dict) or delta.get("tool_calls"):
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
                                    if reason != "stop":
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
