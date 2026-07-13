from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store, StoreMember, User


async def list_accessible_stores(session: AsyncSession, user: User) -> list[Store]:
    query = select(Store).where(Store.is_active.is_(True)).order_by(Store.name)
    if user.role != "admin":
        query = query.join(StoreMember).where(StoreMember.user_id == user.id)
    return list((await session.scalars(query)).all())
