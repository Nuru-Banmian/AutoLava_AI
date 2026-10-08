"""Validate model proposals against current authority in short SQLite transactions."""
import re
import unicodedata
from uuid import uuid4

from sqlalchemy import select, text
from fastapi import HTTPException

from app.agents.memory.repository import read_memories, read_sources, scoped_memories, scope_revision
from app.agents.providers.bailian import ModelFailure
from app.core.database import sqlite_short_write
from app.models.agent import (
    AgentEvent, AgentMemory, AgentMemoryIndex, AgentMemorySource, AgentMemoryScope, AgentMemoryChange,
)
from app.schemas.memory import MemoryItem
from app.models.identity import Store
from app.services.sessions import utc_now


def explicit_content(text):
    match = re.match(r"^(?:请)?(?:帮我)?(?:记住|记下|记得)[：:,，\s]*(.+)$", text.strip(), re.S)
    return match.group(1).strip() if match else None


def normalized(text):
    # Decimal points, signs and other punctuation can change a fact's meaning.
    return unicodedata.normalize("NFKC", text).strip()


class MemoryService:
    def __init__(self, storage, index=None):
        self.storage = storage
        self.index = index

    async def listing(self, scope, before=None):
        async with self.storage.sessions() as session:
            # SQLite's legacy driver mode does not BEGIN for SELECT. Keep the
            # displayed records and their clear precondition in one DB snapshot.
            await session.execute(text("BEGIN"))
            await scope.authorize(session)
            result = await read_memories(session, scope, before)
        if self.index is not None:
            result["retrieval_status"] = (await self.index.status(scope))["status"]
        return result

    async def _advance(self, session, scope):
        state = await session.get(AgentMemoryScope, (scope.user_id, scope.store_id))
        if state is None:
            state = AgentMemoryScope(user_id=scope.user_id, store_id=scope.store_id, revision=0)
            session.add(state)
        state.revision += 1

    async def _index(self, session, memory):
        index = await session.get(AgentMemoryIndex, memory.id)
        if index is None:
            index = AgentMemoryIndex(memory_id=memory.id)
            session.add(index)
        index.version = memory.version
        index.status = "pending"
        index.attempts = 0
        index.operation = "delete" if memory.deleted else "upsert"

    async def change(self, scope, memory_id, expected_version, content=None):
        async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            memory = await session.scalar(scoped_memories(scope).where(AgentMemory.id == memory_id))
            if memory is None:
                raise HTTPException(404, "Memory not found")
            if memory.version != expected_version:
                current = (await read_memories(session, scope, memory_id=memory_id))["items"][0]
                raise HTTPException(409, {
                    "message": "记忆已更新，请核对当前记录和你的输入后再保存。",
                    "current": MemoryItem.model_validate(current).model_dump(mode="json"),
                })
            if content is not None:
                session.add(AgentMemoryChange(memory_id=memory.id, version=memory.version + 1,
                                             previous_content=memory.content, content=content))
                memory.content = content
            else:
                memory.deleted = True
            memory.version += 1
            memory.updated_at = utc_now()
            await self._advance(session, scope)
            if memory.status == "active" or memory.deleted:
                await self._index(session, memory)
            await session.flush()
            if content is not None:
                return (await read_memories(session, scope, memory_id=memory_id))["items"][0]

    async def clear(self, scope, expected_revision):
        async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            if await scope_revision(session, scope) != expected_revision:
                raise HTTPException(409, "记忆已变化，请刷新并核对后再次清空。")
            rows = list(await session.scalars(scoped_memories(scope)))
            for memory in rows:
                memory.deleted = True
                memory.version += 1
                memory.updated_at = utc_now()
                await self._index(session, memory)
            # Advance even an empty scope: old in-flight save proposals must expire.
            await self._advance(session, scope)
            await session.flush()
            return await read_memories(session, scope)

    async def indexed_memory(self, scope, memory_id, version):
        """Index adapters must revalidate every hit against SQLite, including retries."""
        async with self.storage.sessions() as session:
            await scope.authorize(session)
            memory = await session.scalar(scoped_memories(scope).where(
                AgentMemory.id == memory_id, AgentMemory.version == version,
                AgentMemory.status == "active",
            ))
            return {"id": memory.id, "version": memory.version, "content": memory.content} if memory else None

    async def snapshot(self, scope, run_id):
        async with self.storage.sessions() as session:
            run = await self.storage.authorize_run(session, scope, run_id)
            if run.memory_revision != await scope_revision(session, scope):
                raise ModelFailure("memory_version_conflict")
            store = await session.get(Store, scope.store_id)
            memories = list(await session.scalars(scoped_memories(scope).order_by(AgentMemory.id).limit(51)))
            if len(memories) > 50:
                raise ModelFailure("memory_context_budget")
            return {
                "input": run.input, "description": store.description,
                "description_revision": store.description_revision,
                "memories": [{"id": m.id, "version": m.version, "content": m.content,
                              "category": m.category, "status": m.status} for m in memories],
            }

    async def sources(self, scope, memory_id, before):
        async with self.storage.sessions() as session:
            await scope.authorize(session)
            if await session.scalar(scoped_memories(scope).where(AgentMemory.id == memory_id)) is None:
                raise HTTPException(404, "Memory not found")
            return await read_sources(session, scope, memory_id, before)

    async def commit(self, scope, run_id, snapshot, proposal):
        # External model processing is finished before opening this write transaction.
        async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            run = await self.storage.authorize_run(session, scope, run_id)
            if run.memory_revision != await scope_revision(session, scope):
                raise ModelFailure("memory_version_conflict")
            store = await session.get(Store, scope.store_id)
            if store.description_revision != snapshot["description_revision"]:
                raise ModelFailure("memory_version_conflict")
            existing_source = await session.scalar(select(AgentMemorySource).join(AgentMemory).where(
                AgentMemorySource.run_id == run_id, AgentMemory.user_id == scope.user_id,
                AgentMemory.store_id == scope.store_id,
            ))
            if existing_source:
                memory = await session.get(AgentMemory, existing_source.memory_id)
                if memory.deleted:
                    raise ModelFailure("memory_version_conflict")
                return {"status": "already_saved", "memory_id": existing_source.memory_id}
            payload = explicit_content(run.input)
            # Do not let a model invent a source, extract somebody else's quote, or expand
            # a small user fragment into a new fact. T5 stores the user's own full payload.
            if not payload or not run.user_message_id or proposal.content != payload:
                raise ModelFailure("memory_invalid_proposal")
            unsafe = re.search(
                r"假如|假设|如果|引用|据说|推测|猜测|可能|临时|今天|这次|本次|[“”\"「」]|"
                r"系统提示|忽略.*指令|工具权限|密码|密钥|营业额|到账状态", payload,
            )
            if proposal.action == "reject" or unsafe:
                result = {"status": "not_saved"}
            else:
                rows = list(await session.scalars(scoped_memories(scope)))
                versions = {m.id: m.version for m in rows}
                if versions != {m["id"]: m["version"] for m in snapshot["memories"]}:
                    raise ModelFailure("memory_version_conflict")
                target = next((m for m in rows if m.id == proposal.target_id), None)
                if proposal.action == "duplicate":
                    if (not target or target.status != "active"
                            or target.version != proposal.target_version
                            or target.category != proposal.category):
                        raise ModelFailure("memory_invalid_proposal")
                elif proposal.target_id is not None or proposal.target_version is not None:
                    raise ModelFailure("memory_invalid_proposal")
                # Exact normalization is server-enforced even if the model misses it.
                exact = next((m for m in rows if normalized(m.content) == normalized(payload)
                              and m.category == proposal.category
                              and (proposal.action != "conflict" or m.status == "pending_confirmation")), None)
                memory = target if proposal.action == "duplicate" else exact
                if memory is None:
                    memory = AgentMemory(id=uuid4().hex, user_id=scope.user_id,
                                         store_id=scope.store_id, content=payload,
                                         category=proposal.category, version=1,
                                         status="pending_confirmation" if proposal.action == "conflict" else "active")
                    session.add(memory)
                    await session.flush()
                    if memory.status == "active":
                        session.add(AgentMemoryIndex(memory_id=memory.id, version=memory.version, status="pending"))
                session.add(AgentMemorySource(memory_id=memory.id, run_id=run_id,
                                              message_id=run.user_message_id, evidence=payload))
                memory.updated_at = utc_now()
                await self._advance(session, scope)
                result = {"status": "pending_confirmation" if memory.status != "active" else
                          ("already_saved" if exact or target else "saved"),
                          "memory_id": memory.id,
                          "index_status": "pending" if memory.status == "active" else "not_scheduled"}
            # The event and authority/outbox commit together. Later stop/reset only affects chat.
            session.add(AgentEvent(run_id=run_id, kind="memory", payload=result))
            return result
