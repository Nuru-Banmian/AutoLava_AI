"""Validate model proposals against current authority in short SQLite transactions."""
import re
import unicodedata
from uuid import uuid4

from sqlalchemy import select, text
from fastapi import HTTPException

from app.agents.memory.repository import read_memories, read_sources, scoped_memories, scope_revision, scope_epoch
from app.agents.providers.bailian import ModelFailure
from app.core.database import sqlite_short_write
from app.models.agent import (
    AgentEvent, AgentMemory, AgentMemoryIndex, AgentMemorySource, AgentMemoryScope, AgentMemoryChange,
    AgentMemoryJob, AgentMessage,
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

    async def _advance(self, session, scope, *, invalidate=False):
        state = await session.get(AgentMemoryScope, (scope.user_id, scope.store_id))
        if state is None:
            state = AgentMemoryScope(user_id=scope.user_id, store_id=scope.store_id, revision=0, epoch=0)
            session.add(state)
        state.revision += 1
        if invalidate:
            state.epoch += 1

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
            await self._advance(session, scope, invalidate=True)
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
            await self._advance(session, scope, invalidate=True)
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

    async def decide(self, scope, memory_id, expected_version, *, confirm, content=None):
        async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            memory = await session.scalar(select(AgentMemory).where(
                AgentMemory.id == memory_id, AgentMemory.user_id == scope.user_id,
                AgentMemory.store_id == scope.store_id,
            ))
            if memory is None:
                raise HTTPException(404, "Memory not found")
            decision = "confirmed" if confirm else "rejected"
            if (memory.decision == decision and memory.version == expected_version + 1
                    and (not confirm or not memory.deleted)
                    and (content is None or content == memory.content)):
                return (await read_memories(session, scope, memory_id=memory_id))["items"][0] if confirm else None
            if memory.deleted:
                raise HTTPException(404, "Memory not found")
            if memory.version != expected_version or memory.status != "pending_confirmation":
                raise HTTPException(409, "候选已变化，请刷新并核对后再处理。")
            if confirm:
                if memory.target_id:
                    target = await session.scalar(scoped_memories(scope).where(AgentMemory.id == memory.target_id))
                    if target is None or target.version != memory.target_version or target.status != "active":
                        raise HTTPException(409, "原记忆已变化，请核对当前记忆后纠正候选。")
                    target.deleted = True
                    target.version += 1
                    target.updated_at = utc_now()
                    await self._index(session, target)
                if content is not None and content != memory.content:
                    session.add(AgentMemoryChange(memory_id=memory.id, version=memory.version + 1,
                                                 previous_content=memory.content, content=content))
                    memory.content = content
                memory.status = "active"
            else:
                memory.deleted = True
            memory.decision = decision
            memory.version += 1
            memory.updated_at = utc_now()
            await self._advance(session, scope, invalidate=True)
            if confirm:
                await self._index(session, memory)
            await session.flush()
            return (await read_memories(session, scope, memory_id=memory_id))["items"][0] if confirm else None

    async def job_snapshot(self, session, scope, job):
        await self.storage.authorize_generation(session, scope, job.generation)
        run = await self.storage._run(session, scope, job.run_id)
        store = await session.get(Store, scope.store_id)
        if (run.status != "completed" or run.user_message_id != job.message_id
                or job.memory_revision != await scope_revision(session, scope)
                or job.memory_epoch != await scope_epoch(session, scope)
                or store.description_revision != job.description_revision):
            raise ModelFailure("memory_version_conflict")
        memories = list(await session.scalars(scoped_memories(scope).order_by(AgentMemory.id).limit(51)))
        if len(memories) > 50:
            raise ModelFailure("memory_context_budget")
        messages = list(await session.scalars(select(AgentMessage).where(
            AgentMessage.conversation_id == run.conversation_id, AgentMessage.role == "user",
            AgentMessage.id <= job.message_id,
        ).order_by(AgentMessage.id.desc()).limit(12)))
        return {"input": run.input, "message_id": job.message_id,
                "conversation": [{"message_id": m.id, "content": m.content} for m in reversed(messages)],
                "description": store.description, "description_revision": store.description_revision,
                "mode": "background", "memories": [
                    {"id": m.id, "version": m.version, "content": m.content,
                     "category": m.category, "status": m.status} for m in memories]}

    async def commit_job(self, scope, job_id, snapshot, proposal):
        async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            job = await session.get(AgentMemoryJob, job_id)
            if job is None or job.status != "running":
                raise ModelFailure("memory_version_conflict")
            current = await self.job_snapshot(session, scope, job)
            if current != snapshot:
                raise ModelFailure("memory_version_conflict")
            source = await session.scalar(select(AgentMemorySource).where(AgentMemorySource.run_id == job.run_id))
            if source:
                result = {"status": "already_processed"}
            else:
                result = await self._apply_background(session, scope, job, snapshot, proposal)
            # Result and authority commit together; interrupted workers cannot replay a save.
            job.status = "completed"
            job.result = result
            job.error_code = None
            job.updated_at = utc_now()
            return result

    async def _apply_background(self, session, scope, job, snapshot, proposal):
        if proposal.action == "reject":
            return {"status": "not_saved"}
        evidence = proposal.evidence
        if not evidence or evidence not in snapshot["input"]:
            raise ModelFailure("memory_invalid_proposal")
        # Inspect the whole user turn, so extracting a phrase cannot hide a quote,
        # hypothetical or temporary instruction that changes its meaning.
        unsafe = re.search(
            r"假如|假设|如果|引用|据说|临时|今天|这次|本次|[“”\"「」]|"
            r"系统提示|忽略.*指令|工具|你说|助手|分析结果|密码|密钥|营业额|到账状态", snapshot["input"],
        )
        if unsafe or (proposal.category == "store_background" and (
                normalized(evidence) in normalized(snapshot["description"])
                or re.search(r"描述|资料|你说|助手|工具|分析结果", snapshot["input"]))):
            return {"status": "not_saved"}
        candidate = proposal.action in {"conflict", "infer"}
        explicit = re.search(r"以后|今后|一直|习惯|偏好|喜欢|主营|我们店|我的店|更正|纠正|改为", evidence)
        if proposal.action == "duplicate" and not explicit:
            raise ModelFailure("memory_invalid_proposal")
        repeated = proposal.action == "duplicate" and any(
            m["id"] == proposal.target_id and m["version"] == proposal.target_version
            and m["category"] == proposal.category and m["status"] == "active"
            and m["content"] == proposal.content for m in snapshot["memories"])
        if not candidate and (((proposal.content != evidence or not explicit) and not repeated)
                              or re.search(r"可能|猜测|推测|大概|似乎", snapshot["input"])):
            candidate = True
        rows = list(await session.scalars(scoped_memories(scope)))
        target = next((m for m in rows if m.id == proposal.target_id), None)
        if proposal.target_id is not None or proposal.target_version is not None:
            if (not target or target.version != proposal.target_version
                    or target.status != "active" or target.category != proposal.category):
                raise ModelFailure("memory_invalid_proposal")
        if proposal.action in {"duplicate", "update"} and target is None:
            raise ModelFailure("memory_invalid_proposal")
        if proposal.action == "update" and not re.search(r"更正|纠正|改为|不是.+而是", snapshot["input"]):
            candidate = True
        exact = next((m for m in rows if normalized(m.content) == normalized(proposal.content)
                      and m.category == proposal.category
                      and m.status == ("pending_confirmation" if candidate else "active")), None)
        if proposal.action == "duplicate" and not candidate:
            memory = target
        elif proposal.action == "update" and not candidate:
            memory = target
            session.add(AgentMemoryChange(memory_id=memory.id, version=memory.version + 1,
                                         previous_content=memory.content, content=proposal.content))
            memory.content = proposal.content
            memory.version += 1
        else:
            memory = exact
            if memory is None:
                memory = AgentMemory(id=uuid4().hex, user_id=scope.user_id, store_id=scope.store_id,
                                     content=proposal.content, category=proposal.category, version=1,
                                     status="pending_confirmation" if candidate else "active",
                                     target_id=target.id if candidate and target else None,
                                     target_version=target.version if candidate and target else None)
                session.add(memory)
                await session.flush()
        session.add(AgentMemorySource(memory_id=memory.id, run_id=job.run_id,
                                      message_id=job.message_id, evidence=evidence))
        memory.updated_at = utc_now()
        await self._advance(session, scope)
        if memory.status == "active":
            await self._index(session, memory)
        return {"status": "pending_confirmation" if memory.status != "active" else "saved",
                "memory_id": memory.id}

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
            if (not payload or not run.user_message_id or proposal.content != payload
                    or proposal.action not in {"save", "duplicate", "conflict", "reject"}
                    or proposal.evidence is not None):
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
                if proposal.action == "duplicate" or (
                        proposal.action == "conflict" and (
                            proposal.target_id is not None or proposal.target_version is not None)):
                    if (not target or target.status != "active"
                            or target.version != proposal.target_version
                            or target.category != proposal.category):
                        raise ModelFailure("memory_invalid_proposal")
                elif proposal.target_id is not None or proposal.target_version is not None:
                    raise ModelFailure("memory_invalid_proposal")
                # Exact normalization is server-enforced even if the model misses it.
                exact = next((m for m in rows if normalized(m.content) == normalized(payload)
                              and m.category == proposal.category
                              and (proposal.action != "conflict" or (
                                  m.status == "pending_confirmation"
                                  and m.target_id == proposal.target_id
                                  and m.target_version == proposal.target_version))), None)
                memory = target if proposal.action == "duplicate" else exact
                if memory is None:
                    memory = AgentMemory(id=uuid4().hex, user_id=scope.user_id,
                                         store_id=scope.store_id, content=payload,
                                         category=proposal.category, version=1,
                                         status="pending_confirmation" if proposal.action == "conflict" else "active",
                                         target_id=target.id if proposal.action == "conflict" and target else None,
                                         target_version=target.version if proposal.action == "conflict" and target else None)
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
