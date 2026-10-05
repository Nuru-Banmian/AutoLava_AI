from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store
from app.services.owner import is_administrator
from app.services.sessions import require_credentials


@dataclass(frozen=True)
class ChatScope:
    user_id: int
    store_id: int
    auth_identity: str
    session_id: str

    async def authorize(self, session: AsyncSession) -> None:
        user = await require_credentials(session, self.auth_identity, self.session_id)
        if user.id != self.user_id or not is_administrator(user):
            raise HTTPException(403, "Administrator access required")
        # Existing policy: administrators can access every active store.
        store = await session.get(Store, self.store_id, populate_existing=True)
        if store is None or not store.is_active:
            raise HTTPException(404, "Store not found")
