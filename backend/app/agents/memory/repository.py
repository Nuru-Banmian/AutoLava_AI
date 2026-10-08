"""Memory queries stay inside the authorized administrator/store scope."""
from sqlalchemy import select

from app.models.agent import AgentMemory, AgentMemoryIndex, AgentMemorySource, AgentMemoryChange, AgentMemoryScope


async def scope_revision(session, scope):
    state = await session.get(AgentMemoryScope, (scope.user_id, scope.store_id))
    return state.revision if state else 0


def scoped_memories(scope):
    return select(AgentMemory).where(
        AgentMemory.user_id == scope.user_id, AgentMemory.store_id == scope.store_id,
        AgentMemory.deleted.is_(False),
    )


async def read_memories(session, scope, before=None, memory_id=None):
    query = scoped_memories(scope)
    if memory_id is not None:
        query = query.where(AgentMemory.id == memory_id)
    if before:
        query = query.where(AgentMemory.id < before)
    rows = list(await session.scalars(query.order_by(AgentMemory.id.desc()).limit(51)))
    items = []
    for memory in rows[:50]:
        sources = list(await session.scalars(select(AgentMemorySource).where(
            AgentMemorySource.memory_id == memory.id,
        ).order_by(AgentMemorySource.id.desc()).limit(21)))
        index = await session.get(AgentMemoryIndex, memory.id)
        changes = list(await session.scalars(select(AgentMemoryChange).where(
            AgentMemoryChange.memory_id == memory.id,
        ).order_by(AgentMemoryChange.id.desc()).limit(20)))
        items.append({
            "id": memory.id, "content": memory.content, "category": memory.category,
            "status": memory.status, "version": memory.version, "updated_at": memory.updated_at,
            "index_status": index.status if index else "not_scheduled",
            "sources_next_before": sources[19].id if len(sources) > 20 else None,
            "sources": [{"id": source.id, "run_id": source.run_id, "message_id": source.message_id,
                         "evidence": source.evidence, "created_at": source.created_at}
                        for source in sources[:20]],
            "changes": [{"version": change.version, "previous_content": change.previous_content,
                         "content": change.content, "created_at": change.created_at} for change in changes],
        })
    return {"items": items, "next_before": rows[49].id if len(rows) > 50 else None,
            "revision": await scope_revision(session, scope)}


async def read_sources(session, scope, memory_id, before):
    query = select(AgentMemorySource).join(AgentMemory).where(
        AgentMemory.id == memory_id, AgentMemory.user_id == scope.user_id,
        AgentMemory.store_id == scope.store_id,
        AgentMemory.deleted.is_(False),
    )
    if before is not None:
        query = query.where(AgentMemorySource.id < before)
    rows = list(await session.scalars(query.order_by(AgentMemorySource.id.desc()).limit(21)))
    return {"items": [{"id": source.id, "run_id": source.run_id, "message_id": source.message_id,
                       "evidence": source.evidence, "created_at": source.created_at}
                      for source in rows[:20]],
            "next_before": rows[19].id if len(rows) > 20 else None}
