from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, Session, require_admin
from app.agent.release import AgentReleaseStatus, agent_release_status
from app.core.config import Settings, get_settings
from app.core.database import sqlite_short_write
from app.models.operations import AgentSettings
from app.services.access import require_fresh_user
from app.services.owner import is_owner

router = APIRouter(prefix="/admin/agent-settings", tags=["admin"])
Administrator = Annotated[object, Depends(require_admin)]


class AgentSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool


async def agent_enabled(session: Session) -> bool:
    runtime = get_settings()
    release = agent_release_status(runtime)
    stored = await _stored_agent_settings(session)
    return _is_enabled_for_release(stored, runtime, release)


async def _stored_agent_settings(session: Session) -> AgentSettings | None:
    return await session.get(AgentSettings, 1)


def _is_enabled_for_release(
    stored: AgentSettings | None,
    runtime: Settings,
    release: AgentReleaseStatus,
) -> bool:
    if stored is None or not stored.enabled or not release.approved:
        return False
    if runtime.environment.lower() != "production":
        return True
    return (
        release.approval_id is not None
        and stored.release_approval_id == release.approval_id
    )


@router.get("")
async def get_agent_settings(
    session: Session, _actor: Administrator
) -> dict[str, bool]:
    runtime = get_settings()
    release = agent_release_status(runtime)
    stored = await _stored_agent_settings(session)
    return {
        "enabled": _is_enabled_for_release(stored, runtime, release),
        "release_approved": release.approved,
    }


@router.patch("")
async def patch_agent_settings(
    body: AgentSettingsBody, session: Session, actor: CurrentUser
) -> dict[str, bool]:
    actor_id = actor.id
    runtime = get_settings()
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(session, user_id=actor_id)
        if not is_owner(fresh_actor):
            raise HTTPException(403, "只有最终管理员可以控制 Agent")
        release = agent_release_status(runtime)
        if body.enabled and not release.approved:
            raise HTTPException(409, "Agent 发布门禁尚未通过，保持全局关闭")
        stored = await _stored_agent_settings(session)
        approval_id = (
            release.approval_id
            if body.enabled and runtime.environment.lower() == "production"
            else None
        )
        if stored is None:
            stored = AgentSettings(
                id=1,
                enabled=body.enabled,
                release_approval_id=approval_id,
            )
            session.add(stored)
        else:
            stored.enabled = body.enabled
            stored.release_approval_id = approval_id
    return {"enabled": body.enabled, "release_approved": release.approved}
