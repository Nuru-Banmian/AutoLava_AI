from typing import Literal, get_args

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, StoreMember, User


Capability = Literal[
    "ledger.view",
    "ledger.create",
    "ledger.edit",
    "ledger.delete",
    "analytics.view",
    "income_config.manage",
    "users.manage",
    "stores.manage",
]

ROLE_CAPABILITIES: dict[str, frozenset[Capability]] = {
    "user": frozenset(
        {
            "ledger.view",
            "ledger.create",
            "ledger.edit",
            "analytics.view",
        }
    ),
    "admin": frozenset(get_args(Capability)),
}


def has_capability(user: User, capability: Capability) -> bool:
    return capability in ROLE_CAPABILITIES.get(user.role, frozenset())


async def list_accessible_stores(session: AsyncSession, user: User) -> list[Store]:
    query = select(Store).order_by(Store.name)
    if user.role != "admin":
        query = query.where(Store.is_active.is_(True)).join(StoreMember).where(
            StoreMember.user_id == user.id
        )
    return list((await session.scalars(query)).all())
