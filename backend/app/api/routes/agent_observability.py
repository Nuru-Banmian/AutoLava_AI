from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict
from sqlalchemy import select

from app.api.deps import Session, require_final_admin
from app.core.database import sqlite_short_write
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
    run_id: str
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
    occurrence_count: int
    is_resolved: bool
    created_at: datetime
    last_seen_at: datetime
    resolved_at: datetime | None


class AgentAlertStatusBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["open", "resolved"]


Limit = Annotated[int, Query(ge=1, le=500)]


@router.get("/runs", response_model=list[AgentRunStatResponse])
async def list_agent_runs(
    session: Session,
    limit: Limit = 100,
) -> list[AgentRunStat]:
    return list(
        await session.scalars(select(AgentRunStat).order_by(AgentRunStat.id.desc()).limit(limit))
    )


@router.get("/alerts", response_model=list[AgentAlertResponse])
async def list_agent_alerts(
    session: Session,
    limit: Limit = 100,
) -> list[AgentAlert]:
    return list(
        await session.scalars(select(AgentAlert).order_by(AgentAlert.id.desc()).limit(limit))
    )


@router.patch("/alerts/{alert_id}", response_model=AgentAlertResponse)
async def update_agent_alert_status(
    alert_id: int,
    body: AgentAlertStatusBody,
    session: Session,
) -> AgentAlert:
    async with sqlite_short_write(session):
        alert = await session.get(AgentAlert, alert_id, populate_existing=True)
        if alert is None:
            raise HTTPException(404, "Agent alert not found")
        alert.is_resolved = body.status == "resolved"
        alert.resolved_at = datetime.now(UTC).replace(tzinfo=None) if alert.is_resolved else None
        await session.flush()
        return alert
