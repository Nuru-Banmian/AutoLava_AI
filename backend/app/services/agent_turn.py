import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import sqlite_short_write
from app.models.agent import AgentMessage, AgentTurn
from app.models.identity import Store
from app.services.agent_conversation import (
    AGENT_SCOPE_EXPLANATION,
    conversation_messages,
    get_or_create_conversation,
    is_business_scope_question,
    trusted_store_context,
)
from app.services.agent_model import AgentModelAdapter, ModelMessage

TURN_FAILED_MESSAGE = "Agent 本轮处理失败，请稍后重试"
TURN_INTERRUPTED_MESSAGE = "后端进程已重新启动，本轮未自动继续"
_END = object()

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
                await self._persist_completion(active.turn_id, answer)
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

    async def _persist_completion(self, turn_id: int, answer: str) -> None:
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
        import json

        while True:
            event = await active.events.get()
            if event is _END:
                return
            yield (
                json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode()
