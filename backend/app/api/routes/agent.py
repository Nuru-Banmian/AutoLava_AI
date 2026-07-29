from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import Session, require_admin, require_final_admin, require_store_access
from app.core.config import get_settings
from app.core.database import sqlite_short_write
from app.models.agent import AGENT_SYSTEM_SETTINGS_ID, AgentSystemSettings
from app.models.identity import User
from app.schemas.agent import AgentSettingsPatch

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
