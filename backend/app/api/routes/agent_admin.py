from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict

from app.api.deps import CurrentUser, Session, require_admin
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
    settings = await session.get(AgentSettings, 1)
    return settings.enabled if settings is not None else False


@router.get("")
async def get_agent_settings(
    session: Session, _actor: Administrator
) -> dict[str, bool]:
    return {"enabled": await agent_enabled(session)}


@router.patch("")
async def patch_agent_settings(
    body: AgentSettingsBody, session: Session, actor: CurrentUser
) -> dict[str, bool]:
    actor_id = actor.id
    async with sqlite_short_write(session):
        fresh_actor = await require_fresh_user(session, user_id=actor_id)
        if not is_owner(fresh_actor):
            raise HTTPException(403, "只有最终管理员可以控制 Agent")
        settings = await session.get(AgentSettings, 1)
        if settings is None:
            settings = AgentSettings(id=1, enabled=body.enabled)
            session.add(settings)
        else:
            settings.enabled = body.enabled
    return {"enabled": body.enabled}
