import asyncio
import os
from collections.abc import Mapping

from pydantic import ValidationError
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session_factory
from app.core.security import hash_password
from app.models.identity import User
from app.schemas.admin import UserCreate


def _validated_admin(username: str, password: str) -> UserCreate:
    username = username.strip()
    if not username:
        raise RuntimeError("AUTOLAVA_BOOTSTRAP_USERNAME is required")
    if not password or not password.strip():
        raise RuntimeError("AUTOLAVA_BOOTSTRAP_PASSWORD is required and cannot be whitespace")
    try:
        return UserCreate(username=username, password=password, role="admin")
    except ValidationError as exc:
        fields = {error["loc"][0] for error in exc.errors()}
        if "username" in fields:
            raise RuntimeError(
                "AUTOLAVA_BOOTSTRAP_USERNAME must contain 3 to 80 characters"
            ) from None
        raise RuntimeError(
            "AUTOLAVA_BOOTSTRAP_PASSWORD must contain 8 to 128 characters"
        ) from None


def credentials_from_environment(environment: Mapping[str, str]) -> tuple[str, str]:
    credentials = _validated_admin(
        environment.get("AUTOLAVA_BOOTSTRAP_USERNAME", ""),
        environment.get("AUTOLAVA_BOOTSTRAP_PASSWORD", ""),
    )
    return credentials.username, credentials.password


async def create_admin(session: AsyncSession, username: str, password: str) -> bool:
    credentials = _validated_admin(username, password)
    result = await session.execute(
        mysql_insert(User)
        .values(
            username=credentials.username,
            password_hash=hash_password(credentials.password),
            role=credentials.role,
            is_active=True,
            remember_token=None,
        )
        .prefix_with("IGNORE")
    )
    return result.rowcount == 1


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
