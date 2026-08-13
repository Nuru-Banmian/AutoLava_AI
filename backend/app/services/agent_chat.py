from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal, Protocol, TypedDict

import httpx
from langgraph.graph import END, START, StateGraph

from app.core.config import Settings
from app.services.agent_tools import (
    DEFAULT_AGENT_TOOLS,
    AgentToolContext,
    AgentToolRegistry,
)

ToolSchema = Mapping[str, object]


class ToolFunctionCall(TypedDict):
    name: str
    arguments: str


class ToolCall(TypedDict):
    id: str
    type: Literal["function"]
    function: ToolFunctionCall


class ChatMessage(TypedDict, total=False):
    role: Literal["system", "user", "assistant", "tool"]
    content: str
    name: str
    tool_calls: list[ToolCall]
    tool_call_id: str


class ChatState(TypedDict):
    messages: list[ChatMessage]
    tool_context: AgentToolContext
    understanding: ChatMessage
    analysis_messages: list[ChatMessage]
    answer: ChatMessage


class ChatModel(Protocol):
    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[ToolSchema] | None = None,
    ) -> Mapping[str, object] | str: ...


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

    async def complete(
        self,
        messages: Sequence[Mapping[str, object]],
        *,
        tools: Sequence[ToolSchema] | None = None,
    ) -> Mapping[str, object]:
        if not all((self._endpoint, self._model_id, self._api_key)):
            raise ChatModelNotConfiguredError
        headers = {"Authorization": f"Bearer {self._api_key}"}
        if self._region:
            headers["X-DashScope-Region"] = self._region
        request_body: dict[str, object] = {
            "model": self._model_id,
            "messages": list(messages),
        }
        if tools:
            request_body["tools"] = list(tools)
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.post(
                    self._chat_endpoint,
                    headers=headers,
                    json=request_body,
                )
                response.raise_for_status()
                message = response.json()["choices"][0]["message"]
            if not isinstance(message, Mapping):
                raise TypeError
            content = message.get("content")
            tool_calls = message.get("tool_calls")
            if not isinstance(content, str):
                content = "" if isinstance(tool_calls, list) and tool_calls else None
            if content is None or (not content.strip() and not tool_calls):
                raise ValueError
            result: ChatMessage = {"content": content.strip()}
            if isinstance(tool_calls, list) and tool_calls:
                result["tool_calls"] = tool_calls
            return result
        except (httpx.HTTPError, KeyError, IndexError, TypeError, ValueError) as exc:
            raise ChatModelUnavailableError from exc


def _load_analysis_skill() -> str:
    path = Path(__file__).resolve().parents[1] / "agent_skills" / "store_analysis" / "SKILL.md"
    return path.read_text(encoding="utf-8")


UNDERSTANDING_PROMPT = """你是 AutoLava 的理解 Agent。理解用户问题和对话上下文，指出回答所需信息；必要时说明需要追问的时间、门店或指标。聊天主题不设经营范围门禁。不要调用工具，也不要直接给用户最终回答。"""
ANALYSIS_PROMPT = """你是 AutoLava 的分析 Agent。依据下方版本化 Skill 自主决定是否调用可用 Tools。普通聊天不需要数据时不要调用 Tool。不得生成 SQL 或索取数据库及系统安全数据。输出分析消息或标准 tool_calls，不要直接冒充最终回答。

{skill}
"""
ANSWER_PROMPT = """你是 AutoLava 的回答 Agent。根据普通对话消息、理解 Agent 消息、分析 Agent 消息和 Tool Messages 组织简洁可靠的最终中文回答。没有 Tool 数据时也可以正常回答普通问题。需要必要信息时直接向用户追问。不要声称访问了未提供的数据。"""


def _model_message(response: Mapping[str, object] | str) -> ChatMessage:
    if isinstance(response, str):
        content = response.strip()
        if not content:
            raise ChatModelUnavailableError
        return {"role": "assistant", "content": content}
    content = response.get("content", "")
    tool_calls = response.get("tool_calls")
    if not isinstance(content, str) or (
        not content.strip() and not isinstance(tool_calls, list)
    ):
        raise ChatModelUnavailableError
    message: ChatMessage = {"role": "assistant", "content": content.strip()}
    if isinstance(tool_calls, list) and tool_calls:
        message["tool_calls"] = tool_calls
    return message


class AgentChatGraph:
    def __init__(
        self,
        model: ChatModel,
        tool_registry: AgentToolRegistry = DEFAULT_AGENT_TOOLS,
    ) -> None:
        skill = _load_analysis_skill()

        async def understand(state: ChatState) -> dict[str, object]:
            response = await model.complete(
                [{"role": "system", "content": UNDERSTANDING_PROMPT}, *state["messages"]]
            )
            return {"understanding": _model_message(response)}

        async def analyze(state: ChatState) -> dict[str, object]:
            understanding = {**state["understanding"], "name": "understanding_agent"}
            response = await model.complete(
                [
                    {
                        "role": "system",
                        "content": ANALYSIS_PROMPT.format(skill=skill),
                    },
                    *state["messages"],
                    understanding,
                ],
                tools=tool_registry.schemas,
            )
            analysis = _model_message(response)
            analysis_messages = [analysis]
            tool_calls = analysis.get("tool_calls", [])
            if isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if isinstance(tool_call, Mapping):
                        analysis_messages.append(
                            await tool_registry.execute(tool_call, state["tool_context"])
                        )
            return {"analysis_messages": analysis_messages}

        async def answer(state: ChatState) -> dict[str, object]:
            understanding = {**state["understanding"], "name": "understanding_agent"}
            response = await model.complete(
                [
                    {"role": "system", "content": ANSWER_PROMPT},
                    *state["messages"],
                    understanding,
                    *state["analysis_messages"],
                ]
            )
            return {"answer": _model_message(response)}

        builder = StateGraph(ChatState)
        builder.add_node("understanding_agent", understand)
        builder.add_node("analysis_agent", analyze)
        builder.add_node("answer_agent", answer)
        builder.add_edge(START, "understanding_agent")
        builder.add_edge("understanding_agent", "analysis_agent")
        builder.add_edge("analysis_agent", "answer_agent")
        builder.add_edge("answer_agent", END)
        self._graph = builder.compile()

    async def reply(
        self,
        messages: Sequence[ChatMessage],
        *,
        tool_context: AgentToolContext,
    ) -> ChatMessage:
        result = await self._graph.ainvoke(
            {"messages": list(messages), "tool_context": tool_context}
        )
        return result["answer"]
