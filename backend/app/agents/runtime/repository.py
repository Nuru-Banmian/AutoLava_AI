"""Short SQLite transactions; no session escapes into model or SSE waits."""

from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.agents.context import ChatScope
from app.core.database import sqlite_short_write
from app.models.agent import AgentConversation, AgentEvent, AgentMessage, AgentRun
from app.schemas.agent import ChatConversation, ChatMessage, ChatRun


class ChatRepository:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]):
        self.sessions = sessions

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

    async def submit(self, scope: ChatScope, content: str, model: str) -> ChatRun:
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            conversation = await self._conversation(session, scope)
            if conversation is None:
                conversation = AgentConversation(user_id=scope.user_id, store_id=scope.store_id)
                session.add(conversation)
                await session.flush()
            active = await session.scalar(select(AgentRun.id).where(
                AgentRun.conversation_id == conversation.id, AgentRun.status == "running",
            ))
            if active:
                raise HTTPException(409, "当前对话正在处理中，请等待完成")
            session.add(AgentMessage(conversation_id=conversation.id, role="user", content=content))
            run = AgentRun(id=uuid4().hex, conversation_id=conversation.id, model=model)
            session.add(run)
            await session.flush()
            session.add(AgentEvent(run_id=run.id, kind="running", payload={"status": "running"}))
            return ChatRun.model_validate(run)

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
            ).order_by(AgentRun.created_at.desc(), AgentRun.id.desc()).limit(1))
            return ChatConversation(
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
            events = list(await session.scalars(select(AgentEvent).where(
                AgentEvent.run_id == run_id, AgentEvent.id > after,
            ).order_by(AgentEvent.id).limit(1)))
            return [(item.id, item.kind, item.payload) for item in events], run.status

    async def record(self, scope: ChatScope, run_id: str, kind: str, payload: dict):
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            run = await self._run(session, scope, run_id)
            if run.status != "running":
                raise RuntimeError("Run already ended")
            if kind == "delta":
                run.output += payload["text"]
            elif kind == "attempt":
                run.calls += 1
            elif kind == "usage":
                run.usage = payload
            elif kind == "completed":
                run.status = "completed"
                session.add(AgentMessage(conversation_id=run.conversation_id,
                                         role="assistant", content=run.output))
            session.add(AgentEvent(run_id=run_id, kind=kind, payload=payload))

    async def fail(self, scope: ChatScope, run_id: str, code: str):
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
