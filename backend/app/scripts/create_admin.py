import asyncio
import os
from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.security import hash_password
from app.models.identity import User


def credentials_from_environment(environment: Mapping[str, str]) -> tuple[str, str]:
    username = environment.get("AUTOLAVA_BOOTSTRAP_USERNAME", "").strip()
    password = environment.get("AUTOLAVA_BOOTSTRAP_PASSWORD", "")
    if not username:
        raise RuntimeError("AUTOLAVA_BOOTSTRAP_USERNAME is required")
    if not password:
        raise RuntimeError("AUTOLAVA_BOOTSTRAP_PASSWORD is required")
    return username, password


async def create_admin(session: AsyncSession, username: str, password: str) -> bool:
    existing = await session.scalar(select(User).where(User.username == username))
    if existing is not None:
        return False
    session.add(
        User(
            username=username,
            password_hash=hash_password(password),
            role="admin",
            is_active=True,
            remember_token=None,
        )
    )
    await session.flush()
    return True


async def bootstrap() -> bool:
    username, password = credentials_from_environment(os.environ)
    async with async_session_factory() as session:
        async with session.begin():
            return await create_admin(session, username, password)


def main() -> None:
    created = asyncio.run(bootstrap())
    print("Administrator created." if created else "Administrator already exists; unchanged.")


if __name__ == "__main__":
    main()
