from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import Session, require_final_admin
from app.models.agent import AgentAlert, AgentRunStat

router = APIRouter(
    prefix="/admin/agent-observability",
    tags=["admin"],
    dependencies=[Depends(require_final_admin)],
)


class ClosedResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)


class AgentRunStatResponse(ClosedResponse):
    id: int
    user_id: int
    store_id: int
    role: str
    stage: str
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    result: str
    error_category: str | None
    latency_ms: int
    estimated_cost: float | None
    is_fallback: bool
    created_at: datetime


class AgentAlertResponse(ClosedResponse):
    id: int
    alert_type: str
    provider: str
    model: str
    error_category: str
    message: str
    is_resolved: bool
    created_at: datetime
    resolved_at: datetime | None


Limit = Annotated[int, Query(ge=1, le=500)]


@router.get("/runs", response_model=list[AgentRunStatResponse])
async def list_agent_runs(
    session: Session,
    limit: Limit = 100,
) -> list[AgentRunStat]:
    return list(
        await session.scalars(
            select(AgentRunStat).order_by(AgentRunStat.id.desc()).limit(limit)
        )
    )


@router.get("/alerts", response_model=list[AgentAlertResponse])
async def list_agent_alerts(
    session: Session,
    limit: Limit = 100,
) -> list[AgentAlert]:
    return list(
        await session.scalars(
            select(AgentAlert).order_by(AgentAlert.id.desc()).limit(limit)
        )
    )
