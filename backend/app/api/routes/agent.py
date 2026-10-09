import asyncio
import json
from typing import Annotated

import anyio
from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.agents.context import ChatScope
from app.api.deps import Session, StoreAccess, require_admin, require_store_access
from app.models.identity import User
from app.core.database import end_read_transaction
from app.schemas.agent import ChatChart, ChatConversation, ChatGeneration, ChatRun, ChatSubmit
from app.schemas.memory import MemoryList, MemorySourceList, MemoryItem, MemoryCorrection, MemoryVersion, MemoryClear
from app.schemas.memory import MemoryIndexStatus, MemoryIndexScheduled
from app.schemas.memory import MemoryConfirmation, MemoryJobList
from app.services.owner import is_administrator
from app.services.sessions import current_credentials

router = APIRouter(prefix="/agent/{store_id}", tags=["agent"])


async def chat_scope(
    session: Session, admin: Annotated[User, Depends(require_admin)],
    access: Annotated[StoreAccess, Depends(require_store_access)],
) -> ChatScope:
    if not is_administrator(access.user):
        raise HTTPException(403, "Administrator access required")
    credentials = current_credentials.get()
    if credentials is None:
        raise HTTPException(401, "Authentication required")
    scope = ChatScope(access.user.id, access.store.id, *credentials)
    await end_read_transaction(session)
    return scope


Scope = Annotated[ChatScope, Depends(chat_scope)]


@router.get("/memory-index", response_model=MemoryIndexStatus)
async def index_status(request: Request, scope: Scope):
    return await request.app.state.agent_runner.index.status(scope)


@router.post("/memory-index/retry", response_model=MemoryIndexScheduled)
async def retry_index(request: Request, scope: Scope):
    return await request.app.state.agent_runner.index.retry(scope)


@router.post("/memory-index/rebuild", response_model=MemoryIndexScheduled)
async def rebuild_index(request: Request, scope: Scope):
    return await request.app.state.agent_runner.index.retry(scope, rebuild=True)


@router.get("/memory-jobs", response_model=MemoryJobList)
async def memory_jobs(request: Request, scope: Scope, before: int | None = Query(None, ge=1)):
    return await request.app.state.agent_runner.jobs.listing(scope, before)


@router.post("/memories/{memory_id}/confirm", response_model=MemoryItem)
async def confirm_memory(memory_id: str, payload: MemoryConfirmation, request: Request, scope: Scope):
    return await request.app.state.agent_runner.memory.decide(
        scope, memory_id, payload.expected_version, confirm=True, content=payload.content,
    )


@router.post("/memories/{memory_id}/reject", status_code=204)
async def reject_memory(memory_id: str, payload: MemoryVersion, request: Request, scope: Scope):
    await request.app.state.agent_runner.memory.decide(scope, memory_id, payload.expected_version, confirm=False)


@router.get("/memories", response_model=MemoryList)
async def memories(request: Request, scope: Scope, before: str | None = Query(None, pattern=r"^[a-f0-9]{32}$")):
    return await request.app.state.agent_runner.memory.listing(scope, before)


@router.get("/memories/{memory_id}/sources", response_model=MemorySourceList)
async def memory_sources(memory_id: str, request: Request, scope: Scope, before: int | None = Query(None, ge=1)):
    return await request.app.state.agent_runner.memory.sources(scope, memory_id, before)


@router.patch("/memories/{memory_id}", response_model=MemoryItem)
async def correct_memory(memory_id: str, payload: MemoryCorrection, request: Request, scope: Scope):
    return await request.app.state.agent_runner.memory.change(scope, memory_id, payload.expected_version, payload.content)


@router.delete("/memories/{memory_id}", status_code=204)
async def delete_memory(memory_id: str, payload: MemoryVersion, request: Request, scope: Scope):
    await request.app.state.agent_runner.memory.change(scope, memory_id, payload.expected_version)


@router.post("/memories/clear", response_model=MemoryList)
async def clear_memories(payload: MemoryClear, request: Request, scope: Scope):
    return await request.app.state.agent_runner.memory.clear(scope, payload.expected_revision)


@router.get("/conversation", response_model=ChatConversation)
async def conversation(request: Request, scope: Scope, before: int | None = Query(None, ge=1)):
    return await request.app.state.agent_runner.storage.conversation(scope, before)


@router.get("/messages/{message_id}/charts/{chart_id}", response_model=ChatChart)
async def chart_snapshot(message_id: int, chart_id: str, request: Request, scope: Scope):
    return await request.app.state.agent_runner.storage.chart(scope, message_id, chart_id)


@router.post("/messages", response_model=ChatRun, status_code=202)
async def submit(payload: ChatSubmit, request: Request, scope: Scope):
    return await request.app.state.agent_runner.submit(scope, payload.content, payload.request_id, payload.generation)


@router.get("/runs/{run_id}", response_model=ChatRun)
async def run_status(run_id: str, request: Request, scope: Scope):
    return await request.app.state.agent_runner.storage.run(scope, run_id)


@router.post("/runs/{run_id}/stop", response_model=ChatRun)
async def stop(run_id: str, request: Request, scope: Scope):
    return await request.app.state.agent_runner.stop(scope, run_id)


@router.post("/conversation/reset", response_model=ChatConversation)
async def reset(payload: ChatGeneration, request: Request, scope: Scope):
    return await request.app.state.agent_runner.reset(scope, payload.generation)


@router.get("/runs/{run_id}/events", response_class=StreamingResponse)
async def run_events(
    run_id: str, request: Request, scope: Scope,
    after: int = Query(default=0, ge=0),
    last_event_id: Annotated[str | None, Header()] = None,
):
    storage = request.app.state.agent_runner.storage
    await storage.run(scope, run_id)
    if last_event_id is not None:
        if not last_event_id.isdecimal() or len(last_event_id) > 18:
            raise HTTPException(422, "Invalid event cursor")
        after = max(after, int(last_event_id))

    async def stream():
        cursor = after
        while not await request.is_disconnected():
            try:
                # A client can disconnect while this short read closes its session.
                # Finish that cleanup before the streaming task handles cancellation.
                with anyio.CancelScope(shield=True):
                    events, status = await storage.events(scope, run_id, cursor)
            except HTTPException:
                yield 'event: failed\ndata: {"error_code":"access_revoked"}\n\n'
                return
            for event_id, kind, payload in events:
                yield f"id: {event_id}\nevent: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                cursor = event_id
                # EventSource closes on a terminal event. Do not start another
                # database read that would be cancelled during connection cleanup.
                if kind in {"completed", "failed"}:
                    return
            if status != "running" and not events:
                return
            if not events:
                yield ": heartbeat\n\n"
                await asyncio.sleep(0.25)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={
        "Cache-Control": "no-cache", "X-Accel-Buffering": "no",
    })
