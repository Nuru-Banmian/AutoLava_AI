from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: int, remember: bool) -> tuple[str, int]:
    max_age = 30 * 24 * 3600 if remember else 12 * 3600
    payload = {"sub": str(user_id), "exp": datetime.now(UTC) + timedelta(seconds=max_age)}
    secret = get_settings().jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm="HS256"), max_age


def decode_access_token(token: str) -> int:
    secret = get_settings().jwt_secret.get_secret_value()
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"require": ["sub", "exp"]},
    )
    try:
        return int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise jwt.InvalidTokenError("Invalid subject claim") from exc
