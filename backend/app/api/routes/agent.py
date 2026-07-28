from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from app.agent.conversation import (
    AgentRunResult,
    AgentTurnResponse,
    ConversationResponse,
    ConversationState,
    append_message,
    conversation_response,
    create_or_get_conversation,
    delete_conversation,
    get_conversation_by_id,
    recent_model_messages,
)
from app.agent.contracts import ModelMessage
from app.agent.model import CONFIGURATION_CATEGORIES
from app.agent.native import NativeToolAccessDenied
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags
from app.api.deps import CurrentUser, Session
from app.api.routes.agent_admin import agent_enabled
from app.core.database import end_read_transaction, sqlite_short_write
from app.models.agent import AgentAlert, AgentEvidence, AgentRunStat
from app.services.access import require_fresh_store_access, require_fresh_user
from app.services.owner import is_administrator, is_owner

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentTurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)


class AgentResetBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: Literal["permanently_delete"]


class AgentRunner(Protocol):
    async def run(
        self,
        context: RuntimeContext,
        state: ConversationState,
        recent_messages: list[ModelMessage],
    ) -> AgentRunResult: ...


async def _require_agent_administrator(session: Session, user_id: int):
    user = await require_fresh_user(session, user_id=user_id)
    if not is_administrator(user):
        raise HTTPException(403, "Administrator access required")
    return user


@router.get("/status")
async def get_agent_status(session: Session, actor: CurrentUser) -> dict[str, bool]:
    await _require_agent_administrator(session, actor.id)
    return {"enabled": await agent_enabled(session)}


@router.post("/stores/{store_id}/turn")
async def run_agent_turn(
    store_id: int,
    body: AgentTurnBody,
    request: Request,
    session: Session,
    actor: CurrentUser,
) -> AgentTurnResponse:
    user = await _require_agent_administrator(session, actor.id)
    user, store = await require_fresh_store_access(
        session,
        user_id=user.id,
        store_id=store_id,
        capability="analytics.view",
    )
    enabled = await agent_enabled(session)
    if not enabled:
        raise HTTPException(403, "Agent 当前未启用")
    context = RuntimeContext(
        user_id=user.id,
        store_id=store.id,
        role="final_admin" if is_owner(user) else "admin",
        store_timezone=store.timezone,
        features=RuntimeFeatureFlags(
            agent_enabled=enabled,
            company_settlement_enabled=store.company_settlement_enabled,
            income_items_enabled=store.income_items_enabled,
            wash_count_enabled=store.wash_count_enabled,
        ),
    )
    user_id = user.id
    authorized_store_id = store.id
    async with sqlite_short_write(session):
        conversation = await create_or_get_conversation(
            session, user_id=user_id, store_id=authorized_store_id
        )
        await append_message(
            session,
            conversation=conversation,
            role="user",
            content=body.question,
        )
        state = ConversationState.model_validate(conversation.state)
        if state.investigation_goal is None:
            state = state.model_copy(update={"investigation_goal": body.question})
        conversation_id = conversation.id
        recent_messages = await recent_model_messages(session, conversation_id=conversation.id)

    # The model call happens after the short write and outside any SQLite snapshot.
    await end_read_transaction(session)
    runner: AgentRunner = request.app.state.agent_service
    try:
        run_result = await runner.run(context, state, recent_messages)
    except NativeToolAccessDenied as error:
        raise HTTPException(403, "Agent 工具授权已失效") from error
    result = run_result.turn

    async with sqlite_short_write(session):
        user = await _require_agent_administrator(session, user_id)
        await require_fresh_store_access(
            session,
            user_id=user.id,
            store_id=authorized_store_id,
            capability="analytics.view",
        )
        current_conversation = await get_conversation_by_id(
            session,
            conversation_id=conversation_id,
            user_id=user_id,
            store_id=authorized_store_id,
        )
        if current_conversation is None:
            raise HTTPException(409, "当前对话已被重置")
        current_conversation.state = run_result.state.model_dump(mode="json")
        if run_result.evidence is not None:
            session.add(
                AgentEvidence(
                    conversation_id=current_conversation.id,
                    payload=run_result.evidence.model_dump(mode="json"),
                )
            )
        for attempt in run_result.attempts:
            session.add(
                AgentRunStat(
                    user_id=user_id,
                    store_id=authorized_store_id,
                    role=context.role,
                    stage=attempt.stage,
                    provider=attempt.provider,
                    model=attempt.model,
                    input_tokens=attempt.input_tokens,
                    output_tokens=attempt.output_tokens,
                    result=attempt.result,
                    error_category=(
                        attempt.error_category.value if attempt.error_category is not None else None
                    ),
                    latency_ms=attempt.latency_ms,
                    estimated_cost=attempt.estimated_cost,
                    is_fallback=attempt.is_fallback,
                )
            )
            if attempt.error_category in CONFIGURATION_CATEGORIES:
                alert_type = (
                    "budget"
                    if attempt.error_category.value == "insufficient_balance"
                    else "configuration"
                )
                session.add(
                    AgentAlert(
                        alert_type=alert_type,
                        provider=attempt.provider,
                        model=attempt.model,
                        error_category=attempt.error_category.value,
                        message=(
                            "模型预算不可用，请检查供应商账户。"
                            if alert_type == "budget"
                            else "模型配置不可用，请检查供应商设置。"
                        ),
                        is_resolved=False,
                    )
                )
        await append_message(
            session,
            conversation=conversation,
            role="assistant",
            content=result.content,
            action=result.action,
        )
        snapshot = await conversation_response(
            session, user_id=user_id, store_id=authorized_store_id
        )
    return AgentTurnResponse(
        route=result.route,
        content=result.content,
        recovery_status=result.recovery_status,
        progress=run_result.progress,
        partial=run_result.partial,
        conversation=snapshot,
    )


@router.get("/stores/{store_id}/conversation")
async def get_current_conversation(
    store_id: int,
    session: Session,
    actor: CurrentUser,
) -> ConversationResponse:
    user = await _require_agent_administrator(session, actor.id)
    user, store = await require_fresh_store_access(
        session,
        user_id=user.id,
        store_id=store_id,
        capability="analytics.view",
    )
    return await conversation_response(session, user_id=user.id, store_id=store.id)


@router.delete("/stores/{store_id}/conversation", status_code=204)
async def reset_current_conversation(
    store_id: int,
    body: AgentResetBody,
    session: Session,
    actor: CurrentUser,
) -> Response:
    del body
    user = await _require_agent_administrator(session, actor.id)
    user, store = await require_fresh_store_access(
        session,
        user_id=user.id,
        store_id=store_id,
        capability="analytics.view",
    )
    user_id = user.id
    authorized_store_id = store.id
    async with sqlite_short_write(session):
        await delete_conversation(session, user_id=user_id, store_id=authorized_store_id)
    return Response(status_code=204)
