from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.native import NativeToolAccessDenied
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags
from app.core.database import end_read_transaction
from app.services.access import require_fresh_store_access, require_fresh_user
from app.services.owner import is_administrator, is_owner

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
AgentEnabled = Callable[[AsyncSession], Awaitable[bool]]


class DatabaseNativeToolScopeResolver:
    """Rebuild the server-owned Agent scope immediately before tool execution."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        agent_enabled: AgentEnabled,
    ) -> None:
        self._session_factory = session_factory
        self._agent_enabled = agent_enabled

    async def refresh(self, context: RuntimeContext) -> RuntimeContext:
        async with self._session_factory() as session:
            try:
                return await self.refresh_in_session(session, context)
            finally:
                await end_read_transaction(session)

    async def refresh_in_session(
        self,
        session: AsyncSession,
        context: RuntimeContext,
    ) -> RuntimeContext:
        try:
            user = await require_fresh_user(session, user_id=context.user_id)
            if not is_administrator(user):
                raise HTTPException(403, "Administrator access required")
            user, store = await require_fresh_store_access(
                session,
                user_id=user.id,
                store_id=context.store_id,
                capability="analytics.view",
            )
            enabled = await self._agent_enabled(session)
            if not enabled:
                raise HTTPException(403, "Agent 当前未启用")
            return RuntimeContext(
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
        except HTTPException as error:
            raise NativeToolAccessDenied("runtime scope is no longer authorized") from error
