from collections.abc import Mapping, Sequence
from operator import add
from typing import Annotated, Protocol, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from app.agent_chat_types import AgentMessageRole
from app.core.config import Settings


class ChatMessage(TypedDict):
    role: AgentMessageRole
    content: str


class ChatState(TypedDict):
    messages: Annotated[list[ChatMessage], add]


class ChatModel(Protocol):
    async def complete(self, messages: Sequence[Mapping[str, str]]) -> str: ...


class ChatModelNotConfiguredError(RuntimeError):
    pass


class ChatModelUnavailableError(RuntimeError):
    pass


class OpenAICompatibleChatModel:
    def __init__(self, settings: Settings) -> None:
        self._endpoint = settings.agent_model_endpoint.rstrip("/")
        self._region = settings.agent_model_region.strip()
        self._model_id = settings.agent_model_id.strip()
        self._api_key = settings.agent_model_api_key.get_secret_value().strip()

    @property
    def _chat_endpoint(self) -> str:
        if self._endpoint.endswith("/chat/completions"):
            return self._endpoint
        return f"{self._endpoint}/chat/completions"

    async def complete(self, messages: Sequence[Mapping[str, str]]) -> str:
        if not all((self._endpoint, self._model_id, self._api_key)):
            raise ChatModelNotConfiguredError
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._region:
            headers["X-DashScope-Region"] = self._region
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    self._chat_endpoint,
                    headers=headers,
                    json={"model": self._model_id, "messages": list(messages)},
                )
                response.raise_for_status()
                payload = response.json()
            content = payload["choices"][0]["message"]["content"]
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ChatModelUnavailableError from exc
        if not isinstance(content, str) or not content.strip():
            raise ChatModelUnavailableError
        return content.strip()


class AgentChatGraph:
    def __init__(self, model: ChatModel) -> None:
        async def call_model(state: ChatState) -> ChatState:
            answer = await model.complete(
                [
                    {
                        "role": "system",
                        "content": "你是 AutoLava AI，一个简洁、可靠的中文助手。",
                    },
                    *state["messages"],
                ]
            )
            return {"messages": [{"role": "assistant", "content": answer}]}

        builder = StateGraph(ChatState)
        builder.add_node("model", call_model)
        builder.add_edge(START, "model")
        builder.add_edge("model", END)
        self._graph = builder.compile()

    async def reply(self, messages: Sequence[ChatMessage]) -> ChatMessage:
        result = await self._graph.ainvoke({"messages": list(messages)})
        return result["messages"][-1]
