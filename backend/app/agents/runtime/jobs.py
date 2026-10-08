"""Single lifecycle owner consumes durable SQLite memory jobs, serially."""
import asyncio
import logging

from fastapi import HTTPException
from sqlalchemy import select

from app.agents.context import ChatScope
from app.agents.providers.bailian import ModelFailure
from app.agents.memory.repository import scope_epoch, scope_revision
from app.core.database import sqlite_short_write
from app.models.agent import AgentMemoryJob
from app.services.sessions import utc_now

logger = logging.getLogger(__name__)


class MemoryJobs:
    def __init__(self, service, settings):
        self.service = service
        self.sessions = service.storage.sessions
        self.settings = settings
        self.task = None
        self.graph = None

    async def start(self):
        if self.task is not None:
            return
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            for job in await session.scalars(select(AgentMemoryJob).where(AgentMemoryJob.status == "running")):
                self._failure(job, "interrupted", retryable=True)
        self.task = asyncio.create_task(self._consume())

    def _failure(self, job, code, *, retryable=False):
        job.failures = [*job.failures[-9:], {"code": code, "attempt": job.attempts}]
        job.error_code = code
        job.updated_at = utc_now()
        job.status = "pending" if (retryable and job.attempts < 2
                                  and job.calls < self.settings.agent_memory_max_calls) else "failed"
        if code in {"memory_version_conflict", "access_revoked"}:
            job.status = "stale"

    async def snapshot(self, scope, job_id):
        async with self.sessions() as session:
            job = await session.get(AgentMemoryJob, job_id)
            return await self.service.job_snapshot(session, scope, job)

    async def record(self, scope, job_id, kind, payload):
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            job = await session.get(AgentMemoryJob, job_id)
            await self.service.job_snapshot(session, scope, job)
            if kind == "memory_attempt":
                if job.calls >= self.settings.agent_memory_max_calls:
                    raise ModelFailure("memory_call_budget")
                job.calls += 1

    async def listing(self, scope, before=None):
        async with self.sessions() as session:
            await scope.authorize(session)
            query = select(AgentMemoryJob).where(
                AgentMemoryJob.user_id == scope.user_id, AgentMemoryJob.store_id == scope.store_id,
            )
            if before is not None:
                query = query.where(AgentMemoryJob.id < before)
            rows = list(await session.scalars(query.order_by(AgentMemoryJob.id.desc()).limit(21)))
            return {"items": rows[:20], "next_before": rows[19].id if len(rows) > 20 else None}

    async def _claim(self):
        async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
            job = await session.scalar(select(AgentMemoryJob).where(
                AgentMemoryJob.status == "pending",
            ).order_by(AgentMemoryJob.id).limit(1))
            if job is not None:
                scope = ChatScope(job.user_id, job.store_id, job.auth_identity, job.session_id)
                # Only queued normal additions may rebase. User mutations and reset
                # remain fenced by the original epoch and conversation generation.
                if job.memory_epoch == await scope_epoch(session, scope):
                    job.memory_revision = await scope_revision(session, scope)
                job.status = "running"
                job.attempts += 1
                job.updated_at = utc_now()
            return job

    async def _consume(self):
        while True:
            try:
                job = await self._claim()
                if job is None:
                    await asyncio.sleep(0.25)
                    continue
                scope = ChatScope(job.user_id, job.store_id, job.auth_identity, job.session_id)
                code, retryable = None, False
                try:
                    async with asyncio.timeout(self.settings.agent_memory_timeout_seconds):
                        await self.graph.ainvoke({"scope": scope, "run_id": job.run_id, "job_id": job.id})
                except ModelFailure as exc:
                    code, retryable = exc.code, exc.retryable
                except HTTPException:
                    code = "access_revoked"
                except TimeoutError:
                    code, retryable = "memory_model_timeout", True
                except asyncio.CancelledError:
                    # Leave running durable work for startup recovery, preserving its budget.
                    raise
                except Exception:
                    code = "internal_error"
                if code:
                    await self._persist_failure(job.id, code, retryable)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("memory_worker_storage_failure")
                await asyncio.sleep(1)

    async def _persist_failure(self, job_id, code, retryable):
        # Retain ownership through transient storage errors; do not strand a
        # running job or repeat its model call just because status writing failed.
        while True:
            try:
                async with self.sessions() as session, sqlite_short_write(session, begin_immediate=True):
                    current = await session.get(AgentMemoryJob, job_id)
                    if current is not None and current.status == "running":
                        self._failure(current, code, retryable=retryable)
                return
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.error("memory_job_failure_status_unavailable job_id=%s", job_id)
                await asyncio.sleep(1)

    async def close(self):
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
