import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
import json
import logging
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import sqlite_short_write
from app.models.agent import AgentInvestigationCard, AgentMessage, AgentTurn
from app.models.identity import Store
from app.services.agent_calculation import calculate
from app.services.agent_conversation import (
    AGENT_SCOPE_EXPLANATION,
    conversation_messages,
    get_or_create_conversation,
    is_business_scope_question,
    trusted_store_context,
)
from app.services.agent_data_tools import (
    AgentDataToolRegistry,
    DataToolContext,
)
from app.services.agent_model import (
    AgentModelAdapter,
    ModelMessage,
    ModelResponse,
    ModelTool,
)
from app.services.agent_skills import SkillCatalog

TURN_FAILED_MESSAGE = "Agent 本轮处理失败，请稍后重试"
TURN_INTERRUPTED_MESSAGE = "后端进程已重新启动，本轮未自动继续"
_END = object()
logger = logging.getLogger(__name__)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
AdapterFactory = Callable[[], AgentModelAdapter]
TurnEvent = dict[str, Any]


class ActiveAgentTurnError(RuntimeError):
    pass


class AgentTurnStartTimeoutError(RuntimeError):
    pass


@dataclass
class _ActiveTurn:
    turn_id: int
    events: asyncio.Queue[TurnEvent | object]
    task: asyncio.Task[None] | None = None


def _finished_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def latest_conversation_turn(
    session: AsyncSession,
    conversation_id: int,
) -> AgentTurn | None:
    return await session.scalar(
        select(AgentTurn)
        .where(AgentTurn.conversation_id == conversation_id)
        .order_by(AgentTurn.id.desc())
        .limit(1)
    )


class AgentTurnRuntime:
    def __init__(
        self,
        session_factory: SessionFactory,
        adapter_factory: AdapterFactory,
        *,
        turn_timeout_seconds: float = 120,
    ) -> None:
        self._session_factory = session_factory
        self._adapter_factory = adapter_factory
        self._turn_timeout_seconds = turn_timeout_seconds
        self._data_tools = AgentDataToolRegistry(session_factory)
        self._skills = SkillCatalog(self._data_tools.names)
        self._active: dict[tuple[int, int], _ActiveTurn] = {}
        self._starting: set[tuple[int, int]] = set()
        self._lock = asyncio.Lock()

    async def recover_interrupted_turns(self) -> None:
        async with self._session_factory() as session:
            async with sqlite_short_write(session):
                await session.execute(
                    update(AgentTurn)
                    .where(AgentTurn.status == "running")
                    .values(
                        status="interrupted",
                        error_message=TURN_INTERRUPTED_MESSAGE,
                        finished_at=_finished_now(),
                    )
                )

    async def start(
        self,
        *,
        user_id: int,
        store_id: int,
        content: str,
    ) -> AsyncIterator[bytes]:
        key = (user_id, store_id)
        deadline = (
            asyncio.get_running_loop().time()
            + self._turn_timeout_seconds
        )
        async with self._lock:
            if key in self._active or key in self._starting:
                raise ActiveAgentTurnError
            self._starting.add(key)

        try:
            async with asyncio.timeout_at(deadline):
                turn_id, model_messages, direct_answer = (
                    await self._persist_start(
                        user_id=user_id,
                        store_id=store_id,
                        content=content,
                    )
                )
            active = _ActiveTurn(turn_id=turn_id, events=asyncio.Queue())
            async with self._lock:
                self._active[key] = active
                self._starting.remove(key)
                active.task = asyncio.create_task(
                    self._run(
                        key=key,
                        active=active,
                        model_messages=model_messages,
                        direct_answer=direct_answer,
                        deadline=deadline,
                    )
                )
        except TimeoutError as exc:
            async with self._lock:
                self._starting.discard(key)
            raise AgentTurnStartTimeoutError from exc
        except BaseException:
            async with self._lock:
                self._starting.discard(key)
            raise

        return self._event_stream(active)

    async def stop(self) -> None:
        async with self._lock:
            tasks = [
                active.task
                for active in self._active.values()
                if active.task is not None
            ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _persist_start(
        self,
        *,
        user_id: int,
        store_id: int,
        content: str,
    ) -> tuple[int, list[ModelMessage], str | None]:
        async with self._session_factory() as session:
            store = await session.get(Store, store_id)
            if store is None:
                raise RuntimeError("Agent current store disappeared")
            system_context = trusted_store_context(store)
            system_context["content"] += (
                "\n\n可按需加载的数据 Skill：\n"
                f"{self._skills.summaries()}\n"
                "先调用 load_skill 获取完整规则，再调用该 Skill 允许的数据工具。"
            )
            conversation = await get_or_create_conversation(
                session,
                user_id=user_id,
                store_id=store_id,
            )
            conversation_id = conversation.id
            history = await conversation_messages(session, conversation_id)
            model_messages: list[ModelMessage] = [
                system_context,
                *(
                    {"role": message.role, "content": message.content}
                    for message in history
                ),
                {"role": "user", "content": content},
            ]
            direct_answer = (
                None
                if is_business_scope_question(content)
                else AGENT_SCOPE_EXPLANATION
            )
            async with sqlite_short_write(session):
                user_message = AgentMessage(
                    conversation_id=conversation_id,
                    role="user",
                    content=content,
                )
                session.add(user_message)
                await session.flush()
                turn = AgentTurn(
                    conversation_id=conversation_id,
                    user_message_id=user_message.id,
                    status="running",
                )
                session.add(turn)
                await session.flush()
                turn_id = turn.id
        return turn_id, model_messages, direct_answer

    async def _run(
        self,
        *,
        key: tuple[int, int],
        active: _ActiveTurn,
        model_messages: Sequence[ModelMessage],
        direct_answer: str | None,
        deadline: float,
    ) -> None:
        chunks: list[str] = []
        try:
            async with asyncio.timeout_at(deadline):
                await active.events.put(
                    {"type": "started", "turn_id": active.turn_id}
                )
                if direct_answer is not None:
                    await active.events.put(
                        {
                            "type": "phase",
                            "turn_id": active.turn_id,
                            "phase": "preparing_answer",
                        }
                    )
                    chunks.append(direct_answer)
                    await active.events.put(
                        {
                            "type": "answer_delta",
                            "turn_id": active.turn_id,
                            "delta": direct_answer,
                        }
                    )
                else:
                    await active.events.put(
                        {
                            "type": "phase",
                            "turn_id": active.turn_id,
                            "phase": "querying_data",
                        }
                    )
                    adapter = self._adapter_factory()
                    cards: list[dict[str, Any]] = []
                    if callable(getattr(adapter, "respond", None)):
                        answer, cards = await self._run_tool_loop(
                            adapter=adapter,
                            active=active,
                            model_messages=model_messages,
                            user_id=key[0],
                            store_id=key[1],
                        )
                        chunks.append(answer)
                    else:
                        emitted_answer_phase = False
                        async for chunk in self._model_chunks(
                            adapter,
                            model_messages,
                        ):
                            if not chunk:
                                continue
                            if not emitted_answer_phase:
                                for phase in (
                                    "processing_data",
                                    "preparing_answer",
                                ):
                                    await active.events.put(
                                        {
                                            "type": "phase",
                                            "turn_id": active.turn_id,
                                            "phase": phase,
                                        }
                                    )
                                emitted_answer_phase = True
                            chunks.append(chunk)
                            await active.events.put(
                                {
                                    "type": "answer_delta",
                                    "turn_id": active.turn_id,
                                    "delta": chunk,
                                }
                            )
                answer = "".join(chunks).strip()
                if not answer:
                    raise ValueError("Agent model returned an empty answer")
                await self._persist_completion(
                    active.turn_id,
                    answer,
                    cards=cards if direct_answer is None else (),
                )
            await active.events.put(
                {"type": "completed", "turn_id": active.turn_id}
            )
        except TimeoutError:
            await self._finish_timed_out_turn(active, chunks)
        except asyncio.CancelledError:
            await self._persist_failure_bounded(
                active.turn_id,
                status="interrupted",
                message=TURN_INTERRUPTED_MESSAGE,
            )
            raise
        except Exception:
            logger.exception("Agent turn failed")
            await self._persist_failure_bounded(
                active.turn_id,
                status="failed",
                message=TURN_FAILED_MESSAGE,
            )
            await active.events.put(
                {
                    "type": "failed",
                    "turn_id": active.turn_id,
                    "message": TURN_FAILED_MESSAGE,
                }
            )
        finally:
            await active.events.put(_END)
            async with self._lock:
                if self._active.get(key) is active:
                    del self._active[key]

    @staticmethod
    def _model_tools() -> tuple[ModelTool, ...]:
        return (
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": "按名称加载一个数据 Skill 的完整规则。",
                    "parameters": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "business_performance_summary",
                    "description": "汇总 Agent 当前门店指定期间的经营表现。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ledger_revenue_trend",
                    "description": "按日或按月返回 Agent 当前门店的台账营业额趋势。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                            "bucket": {
                                "type": "string",
                                "enum": ["day", "month"],
                            },
                        },
                        "required": ["start", "end", "bucket"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "income_composition",
                    "description": "返回收入分类和其他数据的历史构成。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "daily_ledger_detail",
                    "description": "按业务筛选返回有界、可分页的每日台账明细。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                            "operating_statuses": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["营业", "休息", "提前休息"],
                                },
                                "maxItems": 3,
                            },
                            "recorded_weather": {"type": "string"},
                            "events_only": {"type": "boolean"},
                            "event_keyword": {"type": "string"},
                            "missing_wash_count": {"type": "boolean"},
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 50,
                            },
                            "offset": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 10000,
                            },
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "引用本轮结果或标明来源的字面量执行受限十进制计算。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "steps": {
                                "type": "array",
                                "items": {"type": "object"},
                            }
                        },
                        "required": ["steps"],
                        "additionalProperties": False,
                    },
                },
            },
        )

    async def _run_tool_loop(
        self,
        *,
        adapter: AgentModelAdapter,
        active: _ActiveTurn,
        model_messages: Sequence[ModelMessage],
        user_id: int,
        store_id: int,
    ) -> tuple[str, list[dict[str, Any]]]:
        messages = list(model_messages)
        loaded_skills = {}
        results: dict[str, dict[str, Any]] = {}
        cards: list[dict[str, Any]] = []
        result_number = 0
        for _round in range(8):
            response: ModelResponse = await adapter.respond(
                messages,
                self._model_tools(),
            )
            if not response.tool_calls:
                answer = (response.content or "").strip()
                if not answer:
                    raise ValueError("Agent model returned an empty answer")
                for phase in ("processing_data", "preparing_answer"):
                    await active.events.put(
                        {
                            "type": "phase",
                            "turn_id": active.turn_id,
                            "phase": phase,
                        }
                    )
                await active.events.put(
                    {
                        "type": "answer_delta",
                        "turn_id": active.turn_id,
                        "delta": answer,
                    }
                )
                return answer, cards

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            },
                        }
                        for call in response.tool_calls
                    ],
                }
            )
            for call in response.tool_calls:
                if call.name == "load_skill":
                    if set(call.arguments) != {"name"}:
                        raise ValueError("数据 Skill 加载参数无效")
                    skill = self._skills.load(str(call.arguments["name"]))
                    loaded_skills[skill.name] = skill
                    tool_result = {
                        "name": skill.name,
                        "instructions": skill.instructions,
                        "allowed_data_tools": sorted(
                            skill.allowed_data_tools
                        ),
                    }
                elif call.name in self._data_tools.names:
                    if not any(
                        call.name in skill.allowed_data_tools
                        for skill in loaded_skills.values()
                    ):
                        raise ValueError("数据工具未获得已加载 Skill 授权")
                    result_number += 1
                    result_id = f"result-{result_number}"
                    tool_result = await self._data_tools.execute(
                        call.name,
                        call.arguments,
                        context=DataToolContext(
                            user_id=user_id,
                            store_id=store_id,
                        ),
                        result_id=result_id,
                    )
                    results[result_id] = tool_result
                    card = self._data_tools.investigation_card(
                        call.name,
                        call.arguments,
                        tool_result,
                    )
                    cards.append(card)
                    await active.events.put(
                        {
                            "type": "investigation_card",
                            "turn_id": active.turn_id,
                            "card": card,
                        }
                    )
                elif call.name == "calculate":
                    if set(call.arguments) != {"steps"}:
                        raise ValueError("派生计算参数无效")
                    tool_result = calculate(
                        call.arguments["steps"],
                        results=results,
                    )
                    card = {
                        "operation": "完成派生计算",
                        "range_start": None,
                        "range_end": None,
                        "filters": [],
                        "status": "completed",
                    }
                    cards.append(card)
                    await active.events.put(
                        {
                            "type": "investigation_card",
                            "turn_id": active.turn_id,
                            "card": card,
                        }
                    )
                else:
                    raise ValueError("模型调用了未知工具")
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(
                            tool_result,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                )
        raise ValueError("Agent model loop exceeded its round limit")

    async def _finish_timed_out_turn(
        self,
        active: _ActiveTurn,
        chunks: list[str],
    ) -> None:
        if chunks:
            timeout_note = (
                "\n\n（本轮已达到处理时限，以上为当前可用结果。）"
            )
            chunks.append(timeout_note)
            await active.events.put(
                {
                    "type": "answer_delta",
                    "turn_id": active.turn_id,
                    "delta": timeout_note,
                }
            )
            try:
                async with asyncio.timeout(self._cleanup_timeout_seconds):
                    await self._persist_completion(
                        active.turn_id,
                        "".join(chunks).strip(),
                    )
            except Exception:
                await self._emit_failed_turn(active)
                return
            await active.events.put(
                {
                    "type": "completed",
                    "turn_id": active.turn_id,
                    "partial": True,
                }
            )
            return
        await self._emit_failed_turn(active)

    @property
    def _cleanup_timeout_seconds(self) -> float:
        return min(5.0, max(0.1, self._turn_timeout_seconds))

    async def _emit_failed_turn(self, active: _ActiveTurn) -> None:
        await self._persist_failure_bounded(
            active.turn_id,
            status="failed",
            message=TURN_FAILED_MESSAGE,
        )
        await active.events.put(
            {
                "type": "failed",
                "turn_id": active.turn_id,
                "message": TURN_FAILED_MESSAGE,
            }
        )

    async def _persist_failure_bounded(
        self,
        turn_id: int,
        *,
        status: str,
        message: str,
    ) -> None:
        try:
            async with asyncio.timeout(self._cleanup_timeout_seconds):
                await self._persist_failure(
                    turn_id,
                    status=status,
                    message=message,
                )
        except Exception:
            return

    async def _model_chunks(
        self,
        adapter: AgentModelAdapter,
        model_messages: Sequence[ModelMessage],
    ) -> AsyncIterator[str]:
        for attempt in range(2):
            emitted = False
            try:
                stream = getattr(adapter, "stream", None)
                if stream is None:
                    answer = await adapter.complete(model_messages)
                    emitted = True
                    yield answer
                else:
                    async for chunk in stream(model_messages):
                        emitted = True
                        yield chunk
                return
            except Exception as exc:
                if (
                    attempt == 0
                    and not emitted
                    and self._is_transient_model_error(exc)
                ):
                    continue
                raise

    @staticmethod
    def _is_transient_model_error(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return status == 429 or status >= 500
        return isinstance(exc, httpx.RequestError)

    async def _persist_completion(
        self,
        turn_id: int,
        answer: str,
        *,
        cards: Sequence[dict[str, Any]] = (),
    ) -> None:
        async with self._session_factory() as session:
            turn = await session.get(AgentTurn, turn_id)
            if turn is None:
                raise RuntimeError("Agent turn disappeared")
            if turn.status == "completed":
                return
            conversation_id = turn.conversation_id
            async with sqlite_short_write(session):
                assistant_message = AgentMessage(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                )
                session.add(assistant_message)
                await session.flush()
                for card in cards:
                    session.add(
                        AgentInvestigationCard(
                            turn_id=turn_id,
                            operation=card["operation"],
                            range_start=card["range_start"],
                            range_end=card["range_end"],
                            filters_json=json.dumps(
                                card["filters"],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            status=card["status"],
                        )
                    )
                turn.assistant_message_id = assistant_message.id
                turn.status = "completed"
                turn.error_message = None
                turn.finished_at = _finished_now()

    async def _persist_failure(
        self,
        turn_id: int,
        *,
        status: str,
        message: str,
    ) -> None:
        async with self._session_factory() as session:
            turn = await session.get(AgentTurn, turn_id)
            if turn is None:
                return
            async with sqlite_short_write(session):
                turn.status = status
                turn.error_message = message
                turn.finished_at = _finished_now()

    async def _event_stream(
        self,
        active: _ActiveTurn,
    ) -> AsyncIterator[bytes]:
        while True:
            event = await active.events.get()
            if event is _END:
                return
            yield (
                json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode()
