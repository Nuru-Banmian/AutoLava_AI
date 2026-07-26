from typing import Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from app.agent.contracts import TurnResult
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags
from app.api.deps import CurrentUser, Session
from app.api.routes.agent_admin import agent_enabled
from app.core.database import end_read_transaction
from app.services.access import require_fresh_store_access, require_fresh_user
from app.services.owner import is_administrator, is_owner

router = APIRouter(prefix="/agent", tags=["agent"])


class AgentTurnBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=2_000)


class AgentRunner(Protocol):
    async def run(
        self, context: RuntimeContext, question: str
    ) -> TurnResult: ...


async def _require_agent_administrator(session: Session, user_id: int):
    user = await require_fresh_user(session, user_id=user_id)
    if not is_administrator(user):
        raise HTTPException(403, "Administrator access required")
    return user


@router.get("/status")
async def get_agent_status(
    session: Session, actor: CurrentUser
) -> dict[str, bool]:
    await _require_agent_administrator(session, actor.id)
    return {"enabled": await agent_enabled(session)}


@router.post("/stores/{store_id}/turn")
async def run_agent_turn(
    store_id: int,
    body: AgentTurnBody,
    request: Request,
    session: Session,
    actor: CurrentUser,
) -> TurnResult:
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
    # The model call must not keep a SQLite read snapshot open.
    await end_read_transaction(session)
    runner: AgentRunner = request.app.state.agent_service
    return await runner.run(context, body.question)
