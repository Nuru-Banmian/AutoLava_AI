"""Apply the persisted legacy snapshot once, before serving the new policy."""

import asyncio

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert

from app.core.database import async_session_factory, sqlite_short_write
from app.models.identity import PermissionInitialization, Store, StoreMember, User
from app.services.owner import owner_username

INITIALIZATION_ID = "admin-scope-v1"


async def initialize_permissions(session) -> bool:
    async with sqlite_short_write(session, begin_immediate=True):
        state = await session.get(
            PermissionInitialization, INITIALIZATION_ID, populate_existing=True
        )
        if state is None:
            raise RuntimeError("Run alembic upgrade head before permission initialization")
        if state.completed:
            return False
        owner = (
            await session.scalar(select(User).where(User.username == owner_username()))
            if owner_username()
            else None
        )
        if state.snapshot["users"] and (owner is None or not owner.is_active):
            raise RuntimeError(
                "Valid configured primary administrator required for legacy permissions"
            )
        for legacy in state.snapshot["users"]:
            user = await session.get(User, legacy["id"])
            if user is None or user.username != legacy["username"]:
                raise RuntimeError("Legacy account snapshot no longer matches")
            if user.id == owner.id:
                user.manager_id = None
            elif legacy["role"] == "admin":
                for store_id in state.snapshot["stores"]:
                    if await session.get(Store, store_id) is None:
                        raise RuntimeError("Legacy store snapshot no longer matches")
                    await session.execute(
                        insert(StoreMember)
                        .values(user_id=user.id, store_id=store_id)
                        .on_conflict_do_nothing()
                    )
            else:
                user.manager_id = owner.id
                user.creator_id = owner.id
        state.completed = True
    return True


async def run():
    async with async_session_factory() as session:
        return await initialize_permissions(session)


def main():
    print(
        "Permissions initialized."
        if asyncio.run(run())
        else "Permissions already initialized; unchanged."
    )


if __name__ == "__main__":
    main()
