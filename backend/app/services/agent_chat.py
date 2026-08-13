from collections.abc import Mapping, Sequence
from pathlib import Path
import re
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


UNDERSTANDING_PROMPT = """你是 AutoLava 的理解 Agent。理解用户问题和对话上下文，指出回答所需信息；必要时说明需要追问的时间、门店或指标。聊天主题不设经营范围门禁。不要调用工具，也不要直接给用户最终回答。

第一行必须且只能是以下标记之一：
- STORE_DATA_REQUIRED：回答需要当前门店的经营数据。
- NO_STORE_DATA_REQUIRED：普通聊天、通用知识或仅需追问，不需要当前门店经营数据。

从第二行开始说明你的理解。"""
ANALYSIS_PROMPT = """你是 AutoLava 的分析 Agent。依据下方版本化 Skill 自主决定是否调用可用 Tools。普通聊天不需要数据时不要调用 Tool。不得生成 SQL 或索取数据库及系统安全数据。输出分析消息或标准 tool_calls，不要直接冒充最终回答。

{skill}
"""
ANSWER_PROMPT = """你是 AutoLava 的回答 Agent。根据普通对话消息、理解 Agent 消息、分析 Agent 消息和 Tool Messages 组织简洁可靠的最终中文回答。没有 Tool 数据时也可以正常回答普通问题。需要必要信息时直接向用户追问。不要声称访问了未提供的数据。"""
MAX_ANALYSIS_TOOL_ROUNDS = 4
STORE_DATA_REQUIRED_MARKER = "STORE_DATA_REQUIRED"
ANALYSIS_TOOL_REPAIR_MESSAGE: ChatMessage = {
    "role": "user",
    "content": (
        "协议修复：理解 Agent 已确认回答需要当前门店经营数据，但你尚未调用 Tool。"
        "请立即选择合适的只读 Tool；如需分类 ID 或数据覆盖信息，先调用门店数据目录 Tool。"
    ),
}
STORE_DATA_CONCEPT = re.compile(
    r"营业额|收入分类|公司结算|待到账|应收|每日台账|台账营业额|"
    r"洗车数量|洗车量|平均每车收入|营业状态|记录天气|经营日|事件"
)
STORE_DATA_QUERY_SIGNAL = re.compile(
    r"这周|本周|上周|这个月|本月|上个月|今年|最近|今天|昨天|"
    r"当前门店|这个门店|本店|我们店|多少|哪些|构成|占比|合计|平均|"
    r"趋势|比较|分析|明细|最高|最低|有没有|是否|查询|查看|查一下|看看"
)
STORE_DATA_TIME_SCOPE = re.compile(
    r"这周|本周|上周|这个月|本月|上个月|今年|最近|今天|昨天|"
    r"\d{4}(?:-|年)\d{1,2}"
)
STORE_DATA_QUANTITATIVE_SIGNAL = re.compile(
    r"多少|哪些|构成|占比|合计|一共|平均|趋势|比较|分析|明细|"
    r"最高|最低|涨|跌|分别"
)
GENERIC_CLOSING = re.compile(
    r"不客气|很高兴能帮|如果还有其他|随时找我|需要我为你做些什么|"
    r"有什么需要我帮忙"
)
INVALID_CURRENCY_UNIT = re.compile(r"(?<!欧)元")
SECURITY_DATA_REQUEST = re.compile(
    r"数据库结构|\bSQL\b|模型端点|API\s*Key|密钥|密码|身份凭证|数据库备份",
    re.IGNORECASE,
)
SECURITY_DATA_REFUSAL = (
    "不能提供数据库结构、SQL、模型端点、API Key、密钥、密码、身份凭证或"
    "数据库备份等系统安全数据。你可以询问当前门店的经营数据。"
)
ANSWER_GROUNDING_REPAIR_MESSAGE: ChatMessage = {
    "role": "user",
    "content": (
        "协议修复：你刚才返回了与问题无关的寒暄。必须直接使用已有 Tool Messages "
        "回答用户当前问题；不得忽略数据、改成结束语或声称未取得数据。"
        "所有金额单位必须写欧元或 €，不得写人民币式的“元”。"
    ),
}


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


def _requires_store_data(message: ChatMessage) -> bool:
    first_line = message.get("content", "").strip().splitlines()[0:1]
    return first_line == [STORE_DATA_REQUIRED_MARKER]


def _is_explicit_store_data_question(messages: Sequence[ChatMessage]) -> bool:
    latest_user_content = next(
        (
            message.get("content", "")
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )
    explicit_concept_query = bool(
        STORE_DATA_CONCEPT.search(latest_user_content)
        and STORE_DATA_QUERY_SIGNAL.search(latest_user_content)
    )
    scoped_quantitative_query = bool(
        STORE_DATA_TIME_SCOPE.search(latest_user_content)
        and STORE_DATA_QUANTITATIVE_SIGNAL.search(latest_user_content)
    )
    return explicit_concept_query or scoped_quantitative_query


def _needs_grounding_repair(message: ChatMessage) -> bool:
    content = message.get("content", "")
    generic_without_data = bool(
        GENERIC_CLOSING.search(content) and not re.search(r"\d", content)
    )
    return generic_without_data or bool(INVALID_CURRENCY_UNIT.search(content))


def _security_data_refusal(messages: Sequence[ChatMessage]) -> ChatMessage | None:
    latest_user_content = next(
        (
            message.get("content", "")
            for message in reversed(messages)
            if message.get("role") == "user"
        ),
        "",
    )
    if SECURITY_DATA_REQUEST.search(latest_user_content):
        return {"role": "assistant", "content": SECURITY_DATA_REFUSAL}
    return None


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
            analysis_messages: list[ChatMessage] = []
            store_data_required = _requires_store_data(
                state["understanding"]
            ) or _is_explicit_store_data_question(state["messages"])
            tool_called = False
            for _ in range(MAX_ANALYSIS_TOOL_ROUNDS):
                response = await model.complete(
                    [
                        {
                            "role": "system",
                            "content": ANALYSIS_PROMPT.format(skill=skill),
                        },
                        *state["messages"],
                        understanding,
                        *analysis_messages,
                    ],
                    tools=tool_registry.schemas,
                )
                analysis = _model_message(response)
                analysis_messages.append(analysis)
                tool_calls = analysis.get("tool_calls", [])
                if not isinstance(tool_calls, list) or not tool_calls:
                    if store_data_required and not tool_called:
                        analysis_messages.append(ANALYSIS_TOOL_REPAIR_MESSAGE)
                        continue
                    break
                for tool_call in tool_calls:
                    if isinstance(tool_call, Mapping):
                        tool_called = True
                        analysis_messages.append(
                            await tool_registry.execute(tool_call, state["tool_context"])
                        )
            if store_data_required and not tool_called:
                raise ChatModelUnavailableError
            return {"analysis_messages": analysis_messages}

        async def answer(state: ChatState) -> dict[str, object]:
            understanding = {**state["understanding"], "name": "understanding_agent"}
            answer_messages: list[ChatMessage] = [
                {"role": "system", "content": ANSWER_PROMPT},
                *state["messages"],
                understanding,
                *state["analysis_messages"],
            ]
            has_tool_result = any(
                message.get("role") == "tool"
                for message in state["analysis_messages"]
            )
            for attempt in range(2):
                response = await model.complete(answer_messages)
                answer_message = _model_message(response)
                if not has_tool_result or not _needs_grounding_repair(answer_message):
                    return {"answer": answer_message}
                if attempt == 0:
                    answer_messages.extend(
                        [answer_message, ANSWER_GROUNDING_REPAIR_MESSAGE]
                    )
            raise ChatModelUnavailableError

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
        refusal = _security_data_refusal(messages)
        if refusal is not None:
            return refusal
        result = await self._graph.ainvoke(
            {"messages": list(messages), "tool_context": tool_context}
        )
        return result["answer"]
