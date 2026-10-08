"""One bounded worker, durable SQLite outbox, external calls outside transactions."""
import asyncio

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.memory.repository import scoped_memories
from app.agents.providers.bailian import ModelFailure
from app.agents.providers.embedding import BailianEmbedding
from app.agents.providers.qdrant import MemoryVectors
from app.core.database import sqlite_short_write
from app.models.agent import AgentIndexConfiguration, AgentMemory, AgentMemoryIndex, AgentMemoryScope


class MemoryIndex:
    def __init__(self, storage, settings, *, embedding=None, vectors=None):
        self.storage = storage
        self.settings = settings
        self.embedding = embedding if embedding is not None else BailianEmbedding(settings)
        self.vectors = vectors if vectors is not None else MemoryVectors(settings)
        self.enabled = bool((settings.agent_vector_path or settings.agent_vector_url)
                            and settings.agent_embedding_model and settings.agent_embedding_dimensions)
        self.lock = asyncio.Lock()
        self.task = None
        self.error = None

    def start(self):
        if self.enabled and self.task is None:
            self.task = asyncio.create_task(self._work())

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        async with self.lock:
            await self.vectors.close()

    async def _prepare(self, *, force=False):
        fingerprint = self.vectors.fingerprint
        async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            config = await session.get(AgentIndexConfiguration, 1)
            if config is None:
                config = AgentIndexConfiguration(id=1, target="", active="")
                session.add(config)
            if config.target == fingerprint and not force:
                return
            changed = config.target != fingerprint
            config.target = fingerprint
            config.active = ""
            rows = list(await session.scalars(select(AgentMemory).where(
                AgentMemory.status == "active")))
            for memory in rows:
                job = await session.get(AgentMemoryIndex, memory.id)
                if job is None:
                    job = AgentMemoryIndex(memory_id=memory.id)
                    session.add(job)
                elif not changed and job.status != "ready":
                    # Repeated collection-create failures must not reset retry budgets.
                    continue
                job.version = memory.version
                job.operation = "delete" if memory.deleted else "upsert"
                job.status, job.attempts, job.fingerprint = "pending", 0, ""

    async def _step(self):
        async with self.lock:
            await self._prepare()
            async with self.storage.sessions() as session:
                unfinished = list(await session.scalars(select(AgentMemoryIndex.attempts).where(
                    AgentMemoryIndex.status != "ready")))
            if unfinished and all(n >= self.settings.agent_index_max_attempts for n in unfinished):
                return
            open_error = False
            try:
                await self.vectors.open(before_create=lambda: self._prepare(force=True))
            except Exception:
                open_error = True
            async with self.storage.sessions() as session:
                job = await session.scalar(select(AgentMemoryIndex).where(
                    AgentMemoryIndex.status != "ready",
                    AgentMemoryIndex.attempts < self.settings.agent_index_max_attempts,
                ).order_by(AgentMemoryIndex.attempts, AgentMemoryIndex.memory_id).limit(1))
                if job is None:
                    await session.rollback()
                    # Activate only after every authoritative active record was indexed.
                    if open_error:
                        raise ModelFailure("vector_unavailable")
                    async with sqlite_short_write(session, begin_immediate=True):
                        pending = await session.scalar(select(AgentMemory.id).outerjoin(AgentMemoryIndex).where(
                            AgentMemory.deleted.is_(False), AgentMemory.status == "active",
                            ((AgentMemoryIndex.memory_id.is_(None)) | (AgentMemoryIndex.status != "ready")
                             | (AgentMemoryIndex.version != AgentMemory.version)
                             | (AgentMemoryIndex.fingerprint != self.vectors.fingerprint)),
                        ).limit(1))
                        if pending is None:
                            config = await session.get(AgentIndexConfiguration, 1)
                            config.active = self.vectors.fingerprint
                    return
                memory = await session.get(AgentMemory, job.memory_id)
                item = {"id": memory.id, "version": memory.version, "content": memory.content,
                        "user_id": memory.user_id, "store_id": memory.store_id}
                version, operation = job.version, job.operation
                delete = memory.deleted or memory.status != "active" or operation == "delete"
            error = None
            try:
                if open_error:
                    raise ModelFailure("vector_unavailable")
                if delete:
                    await self.vectors.delete(item["id"])
                else:
                    vector = await self.embedding.embed(item["content"])
                    await self.vectors.put(item, vector)
                    if not await self.vectors.verify(item):
                        raise ModelFailure("vector_verification")
            except Exception as exc:
                error = exc.code if isinstance(exc, ModelFailure) else "vector_unavailable"
            async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
                current = await session.get(AgentMemoryIndex, item["id"])
                # A concurrent correction/delete owns a new job; never acknowledge the old one.
                if current is not None and current.version == version and current.operation == operation:
                    current.attempts += 1
                    current.status = "failed" if error else "ready"
                    current.fingerprint = self.vectors.fingerprint
                    if error:
                        current.error_code = error

    async def _work(self):
        while True:
            try:
                await self._step()
                self.error = None
            except asyncio.CancelledError:
                raise
            except Exception:
                # Never persist exception bodies (provider errors may contain credentials/text).
                self.error = "vector_unavailable"
            await asyncio.sleep(self.settings.agent_index_poll_seconds)

    async def retry(self, scope, *, rebuild=False):
        async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await scope.authorize(session)
            rows = list(await session.scalars(select(AgentMemoryIndex).join(AgentMemory).where(
                AgentMemory.user_id == scope.user_id, AgentMemory.store_id == scope.store_id,
            )))
            scheduled = 0
            for job in rows:
                if rebuild or job.status == "failed":
                    job.status, job.attempts = "pending", 0
                    scheduled += 1
            return {"scheduled": scheduled}

    async def status(self, scope, *, include_retrieval=True):
        async with self.storage.sessions() as session:
            await scope.authorize(session)
            jobs = list(await session.scalars(select(AgentMemoryIndex).join(AgentMemory).where(
                AgentMemory.user_id == scope.user_id, AgentMemory.store_id == scope.store_id,
            )))
            config = await session.get(AgentIndexConfiguration, 1)
            scope_state = await session.get(AgentMemoryScope, (scope.user_id, scope.store_id))
            retrieval_error = scope_state.retrieval_error if scope_state and include_retrieval else None
            state = ("unavailable" if not self.enabled or self.error else
                     "failed" if retrieval_error or any(j.status == "failed" for j in jobs) else
                     "processing" if any(j.status == "pending" for j in jobs) or config is None
                     or config.active != self.vectors.fingerprint else "available")
            return {"status": state, "error_code": self.error or retrieval_error,
                    "failed": sum(j.status == "failed" for j in jobs),
                    "pending": sum(j.status == "pending" for j in jobs)}

    async def _retrieval_state(self, scope, run_id, error):
        async with self.storage.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            await self.storage.authorize_run(session, scope, run_id)
            state = await session.get(AgentMemoryScope, (scope.user_id, scope.store_id))
            if state is None:
                state = AgentMemoryScope(user_id=scope.user_id, store_id=scope.store_id, revision=0)
                session.add(state)
            state.retrieval_error = error

    async def retrieve(self, scope, run_id):
        # Never hold a SQL read snapshot while embedding or querying the vector service.
        async with self.storage.sessions() as session:
            run = await self.storage.authorize_run(session, scope, run_id)
            query = run.input
        # A previous query failure is observable, but must not prevent a recovery query.
        status = await self.status(scope, include_retrieval=False)
        if status["status"] != "available":
            return {"status": status["status"], "items": []}
        try:
            vector = await self.embedding.embed(query)
            async with self.lock:
                if await self.vectors.open(before_create=lambda: self._prepare(force=True)):
                    return {"status": "processing", "items": []}
                hits = await self.vectors.search(scope, vector)
            async with self.storage.sessions() as session:
                await self.storage.authorize_run(session, scope, run_id)
                items = []
                for hit in hits[:12]:
                    if not isinstance(hit, dict):
                        continue
                    memory = await session.scalar(scoped_memories(scope).where(
                        AgentMemory.id == hit.get("id"), AgentMemory.version == hit.get("version"),
                        AgentMemory.status == "active",
                    ))
                    if memory is not None and memory.id not in {m["id"] for m in items}:
                        items.append({"id": memory.id, "version": memory.version, "content": memory.content})
            await self._retrieval_state(scope, run_id, None)
            return {"status": "available", "items": items[:6]}
        except HTTPException:
            raise
        except Exception as exc:
            error = exc.code if isinstance(exc, ModelFailure) else "vector_unavailable"
            await self._retrieval_state(scope, run_id, error)
            return {"status": "failed", "items": [], "error_code": error}
