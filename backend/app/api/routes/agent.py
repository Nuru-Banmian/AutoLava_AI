from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import delete, select
from starlette.responses import StreamingResponse

from app.api.deps import (
    Session,
    StoreAccess,
    require_admin,
    require_final_admin,
    require_store_access,
)
from app.core.config import get_settings
from app.core.database import sqlite_short_write
from app.models.agent import (
    AGENT_SYSTEM_SETTINGS_ID,
    AgentConversation,
    AgentInvestigationCard,
    AgentSystemSettings,
)
from app.models.identity import User
from app.schemas.agent import (
    AgentConversationResponse,
    AgentInvestigationCardResponse,
    AgentMessageCreate,
    AgentMessageResponse,
    AgentSettingsPatch,
    AgentTurnResponse,
)
from app.services.agent_conversation import (
    conversation_messages,
    get_or_create_conversation,
)
from app.services.agent_turn import (
    ActiveAgentTurnError,
    AgentTurnRuntime,
    AgentTurnStartTimeoutError,
    latest_conversation_turn,
)

router = APIRouter(prefix="/agent", tags=["agent"])
Administrator = Annotated[User, Depends(require_admin)]
FinalAdministrator = Annotated[User, Depends(require_final_admin)]


async def _is_agent_globally_enabled(session: Session) -> bool:
    settings = await session.get(AgentSystemSettings, AGENT_SYSTEM_SETTINGS_ID)
    return settings.enabled if settings is not None else False


def _settings_payload(enabled: bool) -> dict[str, bool]:
    return {
        "enabled": enabled,
        "model_config_ready": get_settings().agent_model_config_ready,
    }


@router.get("/admin/settings")
async def read_agent_settings(
    session: Session,
    _actor: FinalAdministrator,
) -> dict[str, bool]:
    return _settings_payload(await _is_agent_globally_enabled(session))


@router.patch("/admin/settings")
async def patch_agent_settings(
    body: AgentSettingsPatch,
    session: Session,
    _actor: FinalAdministrator,
) -> dict[str, bool]:
    if body.enabled and not get_settings().agent_model_config_ready:
        raise HTTPException(409, "模型配置不完整，无法启用数据分析 Agent")

    async with sqlite_short_write(session):
        settings = await session.get(
            AgentSystemSettings,
            AGENT_SYSTEM_SETTINGS_ID,
        )
        if settings is None:
            settings = AgentSystemSettings(id=AGENT_SYSTEM_SETTINGS_ID)
            session.add(settings)
        settings.enabled = body.enabled

    return _settings_payload(body.enabled)


@router.get("/stores/{store_id}")
async def enter_agent_current_store(
    store_id: int,
    actor: Administrator,
    session: Session,
) -> dict[str, Any]:
    if not await _is_agent_globally_enabled(session):
        raise HTTPException(403, "数据分析 Agent 未启用")
    access = await require_store_access(store_id, actor, session)
    return {
        "store_id": access.store.id,
        "store_name": access.store.name,
    }


async def _current_agent_store(
    store_id: int,
    actor: User,
    session: Session,
) -> StoreAccess:
    if not await _is_agent_globally_enabled(session):
        raise HTTPException(403, "数据分析 Agent 未启用")
    return await require_store_access(store_id, actor, session)


async def _conversation_payload(
    session: Session,
    conversation: AgentConversation,
    *,
    store_name: str,
) -> AgentConversationResponse:
    messages = await conversation_messages(session, conversation.id)
    latest_turn = await latest_conversation_turn(session, conversation.id)
    cards = (
        list(
            await session.scalars(
                select(AgentInvestigationCard)
                .where(AgentInvestigationCard.turn_id == latest_turn.id)
                .order_by(AgentInvestigationCard.id)
            )
        )
        if latest_turn is not None
        else []
    )
    return AgentConversationResponse(
        conversation_id=conversation.id,
        store_id=conversation.store_id,
        store_name=store_name,
        messages=[
            AgentMessageResponse.model_validate(message, from_attributes=True)
            for message in messages
        ],
        latest_turn=(
            AgentTurnResponse(
                **AgentTurnResponse.model_validate(
                    latest_turn,
                    from_attributes=True,
                ).model_dump(exclude={"investigation_cards"}),
                investigation_cards=[
                    AgentInvestigationCardResponse.from_record(card)
                    for card in cards
                ],
            )
            if latest_turn is not None
            else None
        ),
    )


@router.get(
    "/stores/{store_id}/conversation",
    response_model=AgentConversationResponse,
)
async def read_agent_conversation(
    store_id: int,
    actor: Administrator,
    session: Session,
) -> AgentConversationResponse:
    access = await _current_agent_store(store_id, actor, session)
    store_name = access.store.name
    conversation = await get_or_create_conversation(
        session,
        user_id=actor.id,
        store_id=access.store.id,
    )
    return await _conversation_payload(
        session,
        conversation,
        store_name=store_name,
    )


@router.post(
    "/stores/{store_id}/messages",
)
async def send_agent_message(
    store_id: int,
    body: AgentMessageCreate,
    request: Request,
    actor: Administrator,
    session: Session,
) -> StreamingResponse:
    access = await _current_agent_store(store_id, actor, session)
    runtime: AgentTurnRuntime = request.app.state.agent_turn_runtime
    try:
        events = await runtime.start(
            user_id=actor.id,
            store_id=access.store.id,
            content=body.content.strip(),
        )
    except ActiveAgentTurnError as exc:
        raise HTTPException(
            409,
            "当前 Agent 会话已有进行中的轮次",
        ) from exc
    except AgentTurnStartTimeoutError as exc:
        raise HTTPException(
            503,
            "Agent 本轮启动超时，请稍后重试",
        ) from exc
    return StreamingResponse(
        events,
        media_type="application/x-ndjson",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
        },
    )


@router.delete("/stores/{store_id}/conversation", status_code=204)
async def reset_agent_conversation(
    store_id: int,
    actor: Administrator,
    session: Session,
) -> None:
    access = await _current_agent_store(store_id, actor, session)
    actor_id = actor.id
    current_store_id = access.store.id
    async with sqlite_short_write(session):
        await session.execute(
            delete(AgentConversation).where(
                AgentConversation.user_id == actor_id,
                AgentConversation.store_id == current_store_id,
            )
        )
