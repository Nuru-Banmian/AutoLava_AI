from collections.abc import AsyncIterator, Sequence
import json
from typing import Protocol

import httpx

from app.core.config import Settings

ModelMessage = dict[str, str]


class AgentModelAdapter(Protocol):
    async def complete(self, messages: Sequence[ModelMessage]) -> str: ...

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

    async def complete(self, messages: Sequence[ModelMessage]) -> str:
        endpoint = self._endpoint
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "X-DashScope-Region": self._region,
                },
                json={
                    "model": self._model_id,
                    "messages": list(messages),
                },
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

    async def stream(
        self,
        messages: Sequence[ModelMessage],
    ) -> AsyncIterator[str]:
        endpoint = self._endpoint
        if not endpoint.endswith("/chat/completions"):
            endpoint = f"{endpoint}/chat/completions"
        received_content = False
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream(
                "POST",
                endpoint,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "X-DashScope-Region": self._region,
                },
                json={
                    "model": self._model_id,
                    "messages": list(messages),
                    "stream": True,
                },
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line.removeprefix("data:").strip()
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)["choices"][0]["delta"].get(
                            "content"
                        )
                    except (
                        json.JSONDecodeError,
                        KeyError,
                        IndexError,
                        TypeError,
                    ) as exc:
                        raise ValueError(
                            "百炼模型返回了无效流式回答"
                        ) from exc
                    if isinstance(chunk, str) and chunk:
                        received_content = True
                        yield chunk
        if not received_content:
            raise ValueError("百炼模型返回了空回答")
