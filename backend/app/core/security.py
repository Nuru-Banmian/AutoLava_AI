from datetime import UTC, datetime, timedelta
from hashlib import sha256

import bcrypt
import jwt

from app.core.config import get_settings

_LONG_PASSWORD_PREFIX = "$autolava-bcrypt-sha256$v1$"
ACCESS_TOKEN_SECONDS = 24 * 60 * 60


def _long_password_digest(password: str) -> bytes:
    return sha256(password.encode()).digest()


def hash_password(password: str) -> str:
    encoded = password.encode()
    if len(encoded) > 72:
        hashed = bcrypt.hashpw(_long_password_digest(password), bcrypt.gensalt()).decode()
        return f"{_LONG_PASSWORD_PREFIX}{hashed}"
    return bcrypt.hashpw(encoded, bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        if password_hash.startswith(_LONG_PASSWORD_PREFIX):
            bcrypt_hash = password_hash.removeprefix(_LONG_PASSWORD_PREFIX)
            return bcrypt.checkpw(_long_password_digest(password), bcrypt_hash.encode())
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except ValueError:
        return False


def create_access_token(user_id: int) -> tuple[str, int]:
    payload = {
        "sub": str(user_id),
        "exp": datetime.now(UTC) + timedelta(seconds=ACCESS_TOKEN_SECONDS),
    }
    secret = get_settings().jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm="HS256"), ACCESS_TOKEN_SECONDS


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
