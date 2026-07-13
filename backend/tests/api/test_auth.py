from importlib import import_module

import bcrypt
import jwt
import pytest
from fastapi import HTTPException

from app.api.routes import auth as auth_routes
from app.core.config import get_settings
from app.models.identity import StoreMember


def load_feature_module(name: str):
    try:
        return import_module(name)
    except ModuleNotFoundError:
        pytest.fail(f"Required feature module {name} does not exist")


async def test_login_sets_http_only_cookie(client, user_factory) -> None:
    await user_factory(username="maria", password="secret", role="user")
    response = await client.post(
        "/api/auth/login",
        json={
            "username": "maria",
            "password": "secret",
            "remember": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["username"] == "maria"
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Max-Age=2592000" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie


async def test_login_sets_session_cookie_attributes(client, user_factory) -> None:
    await user_factory(username="session-user", password="secret")
    response = await client.post(
        "/api/auth/login",
        json={"username": "session-user", "password": "secret", "remember": False},
    )

    assert response.status_code == 200
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "Max-Age=43200" in cookie
    assert "Path=/" in cookie
    assert "SameSite=lax" in cookie


async def test_login_sets_secure_cookie_when_configured(client, user_factory, monkeypatch) -> None:
    monkeypatch.setenv("AUTOLAVA_COOKIE_SECURE", "true")
    get_settings.cache_clear()
    await user_factory(username="secure-user", password="secret")

    response = await client.post(
        "/api/auth/login",
        json={"username": "secure-user", "password": "secret", "remember": False},
    )

    assert response.status_code == 200
    assert "Secure" in response.headers["set-cookie"]


async def test_disabled_user_cannot_login(client, user_factory) -> None:
    await user_factory(username="disabled", password="secret", is_active=False)
    response = await client.post(
        "/api/auth/login",
        json={
            "username": "disabled",
            "password": "secret",
            "remember": False,
        },
    )
    assert response.status_code == 401


async def test_unknown_and_inactive_logins_verify_a_password_hash(
    client, user_factory, monkeypatch
) -> None:
    inactive = await user_factory(username="inactive", password="secret", is_active=False)
    verified_hashes: list[str] = []
    real_verify_password = auth_routes.verify_password

    def tracking_verify_password(password: str, password_hash: str) -> bool:
        verified_hashes.append(password_hash)
        return real_verify_password(password, password_hash)

    monkeypatch.setattr(auth_routes, "verify_password", tracking_verify_password)
    responses = [
        await client.post(
            "/api/auth/login",
            json={"username": username, "password": "incorrect", "remember": False},
        )
        for username in ("missing", "missing", inactive.username)
    ]

    assert [response.status_code for response in responses] == [401, 401, 401]
    assert len(verified_hashes) == 3
    assert verified_hashes[0] == verified_hashes[1]
    assert verified_hashes[0] != inactive.password_hash
    assert verified_hashes[2] == inactive.password_hash
    assert verified_hashes[0].startswith("$2b$12$")
    assert len(verified_hashes[0]) == 60
    assert not bcrypt.checkpw(b"incorrect", verified_hashes[0].encode())


async def test_unassigned_store_is_not_exposed(auth_client, store_factory) -> None:
    hidden = await store_factory(name="Hidden")
    response = await auth_client.get("/api/stores/accessible")
    assert response.status_code == 200
    assert hidden.id not in {store["id"] for store in response.json()}


def test_password_and_jwt_primitives() -> None:
    security = load_feature_module("app.core.security")

    password_hash = security.hash_password("secret")
    assert password_hash != "secret"
    assert security.verify_password("secret", password_hash)
    assert not security.verify_password("incorrect", password_hash)

    session_token, session_max_age = security.create_access_token(42, remember=False)
    remember_token, remember_max_age = security.create_access_token(42, remember=True)
    assert session_max_age == 12 * 3600
    assert remember_max_age == 30 * 24 * 3600
    assert jwt.get_unverified_header(session_token)["alg"] == "HS256"
    assert security.decode_access_token(session_token) == 42
    assert security.decode_access_token(remember_token) == 42


def test_decode_requires_expiration_claim() -> None:
    security = load_feature_module("app.core.security")
    secret = get_settings().jwt_secret.get_secret_value()
    token = jwt.encode({"sub": "42"}, secret, algorithm="HS256")

    with pytest.raises(jwt.InvalidTokenError):
        security.decode_access_token(token)


def test_decode_requires_subject_claim() -> None:
    security = load_feature_module("app.core.security")
    secret = get_settings().jwt_secret.get_secret_value()
    token = jwt.encode({"exp": 4102444800}, secret, algorithm="HS256")

    try:
        security.decode_access_token(token)
    except jwt.InvalidTokenError:
        pass
    except (KeyError, TypeError, ValueError):
        pytest.fail("Missing JWT subject must be normalized as an invalid token")
    else:
        pytest.fail("Token without a subject was accepted")


def test_decode_normalizes_malformed_subject() -> None:
    security = load_feature_module("app.core.security")
    secret = get_settings().jwt_secret.get_secret_value()
    token = jwt.encode({"sub": "not-an-integer", "exp": 4102444800}, secret, algorithm="HS256")

    try:
        security.decode_access_token(token)
    except jwt.InvalidTokenError:
        pass
    except (KeyError, TypeError, ValueError):
        pytest.fail("Malformed JWT subject must be normalized as an invalid token")
    else:
        pytest.fail("Token with a malformed subject was accepted")


def test_decode_rejects_expired_token() -> None:
    security = load_feature_module("app.core.security")
    secret = get_settings().jwt_secret.get_secret_value()
    token = jwt.encode({"sub": "42", "exp": 0}, secret, algorithm="HS256")

    with pytest.raises(jwt.ExpiredSignatureError):
        security.decode_access_token(token)


def test_password_verification_fails_closed_for_invalid_bcrypt_inputs() -> None:
    security = load_feature_module("app.core.security")
    password_hash = security.hash_password("secret")

    for password, stored_hash in (
        ("x" * 73, password_hash),
        ("secret", "not-a-bcrypt-hash"),
    ):
        try:
            verified = security.verify_password(password, stored_hash)
        except ValueError:
            pytest.fail("Invalid bcrypt input must fail closed")
        assert not verified


async def test_me_rejects_user_disabled_after_login(client, user_factory, db_session) -> None:
    user = await user_factory(username="later-disabled", password="secret")
    login = await client.post(
        "/api/auth/login",
        json={"username": user.username, "password": "secret", "remember": False},
    )
    assert login.status_code == 200

    user.is_active = False
    await db_session.flush()
    db_session.expunge(user)
    response = await client.get("/api/auth/me")
    assert response.status_code == 401


async def test_logout_clears_cookie_and_session(auth_client) -> None:
    response = await auth_client.post("/api/auth/logout")
    assert response.status_code == 204
    assert "Max-Age=0" in response.headers["set-cookie"]
    assert (await auth_client.get("/api/auth/me")).status_code == 401


async def test_assigned_store_is_exposed(client, user_factory, store_factory, db_session) -> None:
    user = await user_factory(username="member", password="secret")
    assigned = await store_factory(name="Assigned")
    await store_factory(name="Hidden")
    db_session.add(StoreMember(store_id=assigned.id, user_id=user.id))
    await db_session.flush()
    await client.post(
        "/api/auth/login",
        json={"username": user.username, "password": "secret", "remember": False},
    )

    response = await client.get("/api/stores/accessible")
    assert response.status_code == 200
    assert response.json() == [
        {"id": assigned.id, "name": assigned.name, "timezone": assigned.timezone}
    ]


async def test_admin_sees_every_active_store(client, user_factory, store_factory) -> None:
    admin = await user_factory(username="admin", password="secret", role="admin")
    active = await store_factory(name="Active")
    inactive = await store_factory(name="Inactive", is_active=False)
    await client.post(
        "/api/auth/login",
        json={"username": admin.username, "password": "secret", "remember": False},
    )

    response = await client.get("/api/stores/accessible")
    assert response.status_code == 200
    visible_ids = {store["id"] for store in response.json()}
    assert active.id in visible_ids
    assert inactive.id not in visible_ids


async def test_store_dependency_hides_unassigned_store(
    user_factory, store_factory, db_session
) -> None:
    deps = load_feature_module("app.api.deps")
    user = await user_factory(username="outsider", password="secret")
    store = await store_factory(name="Private")

    with pytest.raises(HTTPException) as error:
        await deps.require_store_access(store.id, user, db_session)
    assert error.value.status_code == 404
    assert error.value.detail == "Store not found"


async def test_admin_dependencies_allow_admin(user_factory, store_factory, db_session) -> None:
    deps = load_feature_module("app.api.deps")
    admin = await user_factory(username="root", password="secret", role="admin")
    store = await store_factory(name="Admin Store")

    assert await deps.require_admin(admin) is admin
    access = await deps.require_store_access(store.id, admin, db_session)
    assert access.store is store
    assert access.user is admin


async def test_current_user_does_not_mask_unexpected_decoder_errors(
    monkeypatch, db_session
) -> None:
    deps = load_feature_module("app.api.deps")

    def broken_decoder(token: str) -> int:
        raise ValueError("decoder configuration failure")

    monkeypatch.setattr(deps, "decode_access_token", broken_decoder)
    with pytest.raises(ValueError, match="decoder configuration failure"):
        await deps.get_current_user(db_session, "token")
