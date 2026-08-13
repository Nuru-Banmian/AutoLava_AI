from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.deps import Session, require_admin, require_store_access
from app.models.identity import User
from app.schemas.agent_chat import AgentChatRequest, AgentChatResponse
from app.services.agent_chat import (
    AgentChatGraph,
    ChatModelNotConfiguredError,
    ChatModelUnavailableError,
)

router = APIRouter(prefix="/agent", tags=["agent"])
Administrator = Annotated[User, Depends(require_admin)]


@router.post("/stores/{store_id}/messages", response_model=AgentChatResponse)
async def send_agent_message(
    store_id: int,
    body: AgentChatRequest,
    request: Request,
    actor: Administrator,
    session: Session,
) -> AgentChatResponse:
    await require_store_access(store_id, actor, session)
    graph: AgentChatGraph = request.app.state.agent_chat_graph
    try:
        answer = await graph.reply(
            [message.model_dump() for message in body.messages]
        )
    except ChatModelNotConfiguredError as exc:
        raise HTTPException(503, "AI 模型尚未配置") from exc
    except ChatModelUnavailableError as exc:
        raise HTTPException(503, "AI 模型暂时不可用，请稍后重试") from exc
    return AgentChatResponse(message=answer)
