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


def create_access_token(auth_identity: str, session_id: str) -> tuple[str, int]:
    payload = {
        "sub": auth_identity,
        "sid": session_id,
        "exp": datetime.now(UTC) + timedelta(seconds=ACCESS_TOKEN_SECONDS),
    }
    secret = get_settings().jwt_secret.get_secret_value()
    return jwt.encode(payload, secret, algorithm="HS256"), ACCESS_TOKEN_SECONDS


def decode_access_token(token: str) -> tuple[str, str]:
    secret = get_settings().jwt_secret.get_secret_value()
    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"require": ["sub", "sid", "exp"]},
    )
    identity, session_id = payload["sub"], payload["sid"]
    if not all(
        isinstance(value, str) and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
        for value in (identity, session_id)
    ):
        raise jwt.InvalidTokenError("Invalid identity or session claim")
    return identity, session_id
