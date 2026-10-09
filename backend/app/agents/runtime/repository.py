"""Short SQLite transactions; no session escapes into model or SSE waits."""

from uuid import uuid4
from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.context import ChatScope
from app.agents.tools.context import TemporaryResults
from app.agents.tools.store_catalog import CatalogCache, version
from app.core.database import sqlite_short_write
from app.models.agent import AgentConversation, AgentEvent, AgentMemoryJob, AgentMessage, AgentRun
from app.models.identity import Store
from app.agents.memory.repository import scope_revision, scope_epoch
from app.schemas.agent import ChatConversation, ChatMessage, ChatRun


class ChatRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions
        self.temporary_results = TemporaryResults()
        self.catalogs = CatalogCache()

    async def background(self, scope: ChatScope, run_id: str) -> dict:
        """One authorized snapshot per turn; no DB transaction spans model waits."""
        async with self.sessions() as session:
            await self.authorize_run(session, scope, run_id)
            store = await session.get(Store, scope.store_id)
            cached = self.catalogs.get(scope, (await self._run(session, scope, run_id)).generation, version(store))
            return {
                "source": "stores.description", "store_id": store.id,
                "revision": store.description_revision, "description": store.description,
                "wash_count_enabled": store.wash_count_enabled,
                "company_settlement_enabled": store.company_settlement_enabled,
                "timezone": store.timezone,
                **({"data_catalog": cached} if cached is not None else {}),
                "local_date": datetime.now(ZoneInfo(store.timezone)).date().isoformat(),
                "memories": [],
                "memory_retrieval": "unavailable",
            }

    async def authorize_run(self, session, scope: ChatScope, run_id: str):
        run = await self._run(session, scope, run_id)
        await self.authorize_generation(session, scope, run.generation)
        if run.status != "running":
            raise RuntimeError("Run already ended")
        return run

    async def _conversation(self, session, scope):
        return await session.scalar(select(AgentConversation).where(
            AgentConversation.user_id == scope.user_id, AgentConversation.store_id == scope.store_id,
        ))

    async def _run(self, session, scope, run_id):
        run = await session.scalar(select(AgentRun).join(AgentConversation).where(
            AgentRun.id == run_id, AgentConversation.user_id == scope.user_id,
            AgentConversation.store_id == scope.store_id,
        ))
        if run is None:
            raise HTTPException(404, "Run not found")
        return run

    async def authorize_generation(self, session, scope: ChatScope, generation: int):
        """Use inside the caller's short write transaction after every external wait.

        Memory jobs must carry this generation and check it before committing sources;
        already committed memory lives independently of chat reset.
        """
        await scope.authorize(session)
        conversation = await self._conversation(session, scope)
        if conversation is None or conversation.generation != generation:
            raise HTTPException(409, "对话已重置")
        return conversation

    async def stop(self, scope: ChatScope, run_id: str) -> ChatRun:
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            run = await self._run(session, scope, run_id)
            if run.status == "running":
                run.status = "failed"
                run.error_code = "cancelled"
                session.add(AgentEvent(run_id=run.id, kind="failed", payload={"error_code": "cancelled"}))
            self.temporary_results.release(run_id)
            return ChatRun.model_validate(run)

    async def reset(self, scope: ChatScope, generation: int) -> list[str]:
        self.catalogs.clear(scope)
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            conversation = await self._conversation(session, scope)
            if conversation is None:
                conversation = AgentConversation(user_id=scope.user_id, store_id=scope.store_id)
                session.add(conversation)
                await session.flush()
            if conversation.generation != generation:
                raise HTTPException(409, "对话已重置，请重新读取")
            runs = list(await session.scalars(select(AgentRun).where(
                AgentRun.conversation_id == conversation.id,
            )))
            cutoff = await session.scalar(select(func.max(AgentEvent.id))) or 0
            active = []
            for run in runs:
                self.temporary_results.release(run.id)
                if run.status == "running":
                    active.append(run.id)
                    run.status = "failed"
                    run.error_code = "reset"
                run.input = ""
                run.output = ""
                session.add(AgentEvent(run_id=run.id, kind="failed", payload={"error_code": "reset"}))
            # Allocate terminal cursors before removing content: SQLite may reuse deleted IDs.
            await session.flush()
            await session.execute(delete(AgentEvent).where(
                AgentEvent.run_id.in_([r.id for r in runs]), AgentEvent.id <= cutoff,
            ))
            await session.execute(delete(AgentMessage).where(AgentMessage.conversation_id == conversation.id))
            conversation.generation += 1
            return active

    async def recover(self):
        """Single-process startup: never transparently repeat a provider call."""
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            runs = await session.scalars(select(AgentRun).where(AgentRun.status == "running"))
            for run in runs:
                run.status = "failed"
                run.error_code = "interrupted"
                session.add(AgentEvent(run_id=run.id, kind="failed", payload={"error_code": "interrupted"}))

    async def submit(self, scope: ChatScope, content: str, model: str,
                     request_id: str, generation: int) -> tuple[ChatRun, bool]:
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            conversation = await self._conversation(session, scope)
            if conversation is None:
                conversation = AgentConversation(user_id=scope.user_id, store_id=scope.store_id)
                session.add(conversation)
                await session.flush()
            if conversation.generation != generation:
                raise HTTPException(409, "对话已重置，请重新读取后再发送")
            existing = await session.scalar(select(AgentRun).where(
                AgentRun.conversation_id == conversation.id, AgentRun.request_id == request_id,
            ))
            if existing:
                if existing.input != content or existing.generation != generation:
                    raise HTTPException(409, "请求标识已用于其他消息")
                return ChatRun.model_validate(existing), False
            active = await session.scalar(select(AgentRun.id).where(
                AgentRun.conversation_id == conversation.id, AgentRun.status == "running",
            ))
            if active:
                raise HTTPException(409, "当前对话正在处理中，请等待完成")
            message = AgentMessage(conversation_id=conversation.id, role="user", content=content)
            session.add(message)
            await session.flush()
            run = AgentRun(id=uuid4().hex, conversation_id=conversation.id, model=model,
                           request_id=request_id, generation=generation, input=content,
                           user_message_id=message.id,
                           memory_revision=await scope_revision(session, scope),
                           memory_epoch=await scope_epoch(session, scope))
            session.add(run)
            await session.flush()
            session.add(AgentEvent(run_id=run.id, kind="running", payload={"status": "running"}))
            return ChatRun.model_validate(run), True

    async def conversation(self, scope: ChatScope, before: int | None = None) -> ChatConversation:
        async with self.sessions() as session:
            await scope.authorize(session)
            conversation = await self._conversation(session, scope)
            if conversation is None:
                return ChatConversation(messages=[], run=None)
            query = select(AgentMessage).where(AgentMessage.conversation_id == conversation.id)
            if before is not None:
                query = query.where(AgentMessage.id < before)
            messages = list(await session.scalars(query.order_by(AgentMessage.id.desc()).limit(101)))
            has_more = len(messages) > 100
            messages = messages[:100]
            run = await session.scalar(select(AgentRun).where(
                AgentRun.conversation_id == conversation.id,
                AgentRun.generation == conversation.generation,
            ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1))
            return ChatConversation(
                generation=conversation.generation,
                messages=[ChatMessage.model_validate(item) for item in reversed(messages)],
                run=ChatRun.model_validate(run) if run else None,
                next_before=messages[-1].id if has_more else None,
            )

    async def run(self, scope: ChatScope, run_id: str) -> ChatRun:
        async with self.sessions() as session:
            await scope.authorize(session)
            return ChatRun.model_validate(await self._run(session, scope, run_id))

    async def events(self, scope: ChatScope, run_id: str, after: int):
        async with self.sessions() as session:
            await scope.authorize(session)
            run = await self._run(session, scope, run_id)
            query = select(AgentEvent).where(
                AgentEvent.run_id == run_id, AgentEvent.id > after,
            )
            if run.error_code in {"cancelled", "reset", "access_revoked"}:
                query = query.where(AgentEvent.kind == "failed")
            events = list(await session.scalars(query.order_by(AgentEvent.id).limit(1)))
            return [(item.id, item.kind, item.payload) for item in events], run.status

    async def record(self, scope: ChatScope, run_id: str, kind: str, payload: dict, *, curate=True):
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            run = await self._run(session, scope, run_id)
            await self.authorize_generation(session, scope, run.generation)
            if run.status != "running":
                raise RuntimeError("Run already ended")
            if kind == "delta":
                run.output += payload["text"]
            elif kind in {"attempt", "memory_attempt"}:
                run.calls += 1
            elif kind in {"usage", "memory_usage"}:
                totals = dict(run.usage or {})
                for key, value in payload.items():
                    totals[key] = totals.get(key, 0) + value
                run.usage = totals
            elif kind == "completed":
                run.status = "completed"
                self.temporary_results.release(run_id)
                session.add(AgentMessage(conversation_id=run.conversation_id,
                                         role="assistant", content=run.output))
                if curate:
                    store = await session.get(Store, scope.store_id)
                    session.add(AgentMemoryJob(
                        run_id=run.id, user_id=scope.user_id, store_id=scope.store_id,
                        auth_identity=scope.auth_identity, session_id=scope.session_id,
                        generation=run.generation, message_id=run.user_message_id,
                        memory_revision=run.memory_revision,
                        memory_epoch=run.memory_epoch,
                        description_revision=store.description_revision,
                    ))
            session.add(AgentEvent(run_id=run_id, kind=kind, payload=payload))

    async def fail(self, scope: ChatScope, run_id: str, code: str):
        self.temporary_results.release(run_id)
        # A revoked caller cannot write more content, but its worker must mark failure.
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            try:
                run = await self._run(session, scope, run_id)
            except HTTPException:
                return
            if run.status == "running":
                run.status = "failed"
                run.error_code = code
                session.add(AgentEvent(run_id=run_id, kind="failed", payload={"error_code": code}))
