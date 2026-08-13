from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from sqlalchemy import delete, select

from app.api.deps import Session, require_admin, require_store_access
from app.core.database import sqlite_short_write
from app.models.agent_chat import AgentConversation, AgentMessage
from app.models.identity import User
from app.schemas.agent_chat import (
    AgentChatMessage,
    AgentChatRequest,
    AgentChatResponse,
    AgentConversationResponse,
)
from app.services.agent_chat import (
    AgentChatGraph,
    ChatModelNotConfiguredError,
    ChatModelUnavailableError,
)
from app.services.agent_tools import AgentToolContext

router = APIRouter(prefix="/agent", tags=["agent"])
Administrator = Annotated[User, Depends(require_admin)]


async def _conversation(
    session: Session, *, user_id: int, store_id: int
) -> AgentConversation | None:
    return await session.scalar(
        select(AgentConversation).where(
            AgentConversation.user_id == user_id,
            AgentConversation.store_id == store_id,
        )
    )


async def _messages(
    session: Session, conversation_id: int, *, limit: int | None = None
) -> list[AgentMessage]:
    statement = (
        select(AgentMessage)
        .where(AgentMessage.conversation_id == conversation_id)
        .order_by(AgentMessage.id.desc() if limit is not None else AgentMessage.id)
    )
    if limit is not None:
        statement = statement.limit(limit)
    messages = list((await session.scalars(statement)).all())
    return list(reversed(messages)) if limit is not None else messages


@router.get(
    "/stores/{store_id}/conversation", response_model=AgentConversationResponse
)
async def get_agent_conversation(
    store_id: int,
    actor: Administrator,
    session: Session,
) -> AgentConversationResponse:
    await require_store_access(store_id, actor, session)
    actor_id = actor.id
    conversation = await _conversation(
        session, user_id=actor_id, store_id=store_id
    )
    if conversation is None:
        return AgentConversationResponse(messages=[])
    messages = await _messages(session, conversation.id)
    return AgentConversationResponse(
        messages=[AgentChatMessage(role=item.role, content=item.content) for item in messages]
    )


@router.post("/stores/{store_id}/messages", response_model=AgentChatResponse)
async def send_agent_message(
    store_id: int,
    body: AgentChatRequest,
    request: Request,
    actor: Administrator,
    session: Session,
) -> AgentChatResponse:
    await require_store_access(store_id, actor, session)
    actor_id = actor.id
    conversation = await _conversation(
        session, user_id=actor_id, store_id=store_id
    )
    saved_messages = (
        await _messages(session, conversation.id, limit=19)
        if conversation is not None
        else []
    )
    last_message_id = saved_messages[-1].id if saved_messages else None
    context = [
        {"role": item.role, "content": item.content} for item in saved_messages
    ]
    context.append({"role": "user", "content": body.content})
    graph: AgentChatGraph = request.app.state.agent_chat_graph
    try:
        answer = await graph.reply(
            context,
            tool_context=AgentToolContext(
                session=session,
                user_id=actor_id,
                store_id=store_id,
            ),
        )
    except ChatModelNotConfiguredError as exc:
        raise HTTPException(503, "AI 模型尚未配置") from exc
    except ChatModelUnavailableError as exc:
        raise HTTPException(503, "AI 模型暂时不可用，请稍后重试") from exc
    async with sqlite_short_write(session):
        current = await _conversation(
            session, user_id=actor_id, store_id=store_id
        )
        if current is None:
            if last_message_id is not None:
                raise HTTPException(409, "对话已经发生变化，请重试")
            current = AgentConversation(user_id=actor_id, store_id=store_id)
            session.add(current)
            await session.flush()
        else:
            current_latest = await session.scalar(
                select(AgentMessage.id)
                .where(AgentMessage.conversation_id == current.id)
                .order_by(AgentMessage.id.desc())
                .limit(1)
            )
            if current_latest != last_message_id:
                raise HTTPException(409, "对话已经发生变化，请重试")
        session.add_all(
            [
                AgentMessage(
                    conversation_id=current.id, role="user", content=body.content
                ),
                AgentMessage(
                    conversation_id=current.id,
                    role="assistant",
                    content=answer["content"],
                ),
            ]
        )
    return AgentChatResponse(message=answer)


@router.delete("/stores/{store_id}/conversation", status_code=204)
async def reset_agent_conversation(
    store_id: int,
    actor: Administrator,
    session: Session,
) -> Response:
    await require_store_access(store_id, actor, session)
    actor_id = actor.id
    async with sqlite_short_write(session):
        await session.execute(
            delete(AgentConversation).where(
                AgentConversation.user_id == actor_id,
                AgentConversation.store_id == store_id,
            )
        )
    return Response(status_code=204)
