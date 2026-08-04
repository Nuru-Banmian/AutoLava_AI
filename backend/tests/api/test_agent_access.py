from httpx import AsyncClient
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.identity import StoreMember


async def _login(client: AsyncClient, username: str, password: str = "secret123") -> None:
    response = await client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def _configure_agent_model(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AUTOLAVA_AGENT_MODEL_ENDPOINT", "https://model.example")
    monkeypatch.setenv("AUTOLAVA_AGENT_MODEL_REGION", "eu")
    monkeypatch.setenv("AUTOLAVA_AGENT_MODEL_ID", "model")
    monkeypatch.setenv("AUTOLAVA_AGENT_MODEL_API_KEY", "secret-key")
    get_settings.cache_clear()


@pytest.mark.parametrize(
    ("missing_name", "configured"),
    [
        ("endpoint", {"REGION": "eu", "MODEL_ID": "model", "API_KEY": "key"}),
        ("region", {"ENDPOINT": "https://model.example", "MODEL_ID": "model", "API_KEY": "key"}),
        ("model", {"ENDPOINT": "https://model.example", "REGION": "eu", "API_KEY": "key"}),
        ("api key", {"ENDPOINT": "https://model.example", "REGION": "eu", "MODEL_ID": "model"}),
    ],
)
async def test_final_admin_sees_only_model_readiness_and_cannot_enable_incomplete_config(
    client: AsyncClient,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
    missing_name: str,
    configured: dict[str, str],
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "final-admin")
    for name in ("ENDPOINT", "REGION", "MODEL_ID", "API_KEY"):
        monkeypatch.delenv(f"AUTOLAVA_AGENT_MODEL_{name}", raising=False)
    for name, value in configured.items():
        monkeypatch.setenv(f"AUTOLAVA_AGENT_MODEL_{name}", value)
    get_settings.cache_clear()
    await user_factory(
        username="final-admin",
        password="secret123",
        role="admin",
    )
    await _login(client, "final-admin")

    response = await client.get("/api/agent/admin/settings")

    assert response.status_code == 200, missing_name
    assert response.json() == {
        "enabled": False,
        "model_config_ready": False,
    }
    assert set(response.json()) == {"enabled", "model_config_ready"}

    enabled = await client.patch(
        "/api/agent/admin/settings",
        json={"enabled": True},
    )
    assert enabled.status_code == 409
    assert enabled.json() == {"detail": "模型配置不完整，无法启用数据分析 Agent"}


async def test_only_final_admin_can_change_the_global_agent_switch(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "final-admin")
    _configure_agent_model(monkeypatch)
    await user_factory(username="final-admin", password="secret123", role="admin")
    await user_factory(username="other-admin", password="secret123", role="admin")
    await db_session.commit()

    await _login(client, "other-admin")
    denied_read = await client.get("/api/agent/admin/settings")
    denied_write = await client.patch(
        "/api/agent/admin/settings",
        json={"enabled": True},
    )
    assert denied_read.status_code == 403
    assert denied_write.status_code == 403

    await _login(client, "final-admin")
    enabled = await client.patch(
        "/api/agent/admin/settings",
        json={"enabled": True},
    )
    assert enabled.status_code == 200
    assert enabled.json() == {"enabled": True, "model_config_ready": True}
    assert (await client.get("/api/agent/admin/settings")).json() == enabled.json()

    disabled = await client.patch(
        "/api/agent/admin/settings",
        json={"enabled": False},
    )
    assert disabled.status_code == 200
    assert disabled.json() == {"enabled": False, "model_config_ready": True}


async def test_agent_current_store_entry_is_backend_gated_and_bound_to_access(
    client: AsyncClient,
    db_session: AsyncSession,
    user_factory,
    store_factory,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "final-admin")
    _configure_agent_model(monkeypatch)
    await user_factory(username="final-admin", password="secret123", role="admin")
    await user_factory(username="store-admin", password="secret123", role="admin")
    member = await user_factory(username="member", password="secret123", role="user")
    await user_factory(username="outsider", password="secret123", role="user")
    selected_store = await store_factory(name="当前门店")
    other_store = await store_factory(name="无权门店")
    db_session.add(StoreMember(store_id=selected_store.id, user_id=member.id))
    selected_store_id = selected_store.id
    other_store_id = other_store.id
    await db_session.commit()

    await _login(client, "store-admin")
    disabled = await client.get(f"/api/agent/stores/{selected_store_id}")
    assert disabled.status_code == 403
    assert disabled.json() == {"detail": "数据分析 Agent 未启用"}

    await _login(client, "final-admin")
    assert (
        await client.patch("/api/agent/admin/settings", json={"enabled": True})
    ).status_code == 200

    await _login(client, "store-admin")
    allowed = await client.get(f"/api/agent/stores/{selected_store_id}")
    assert allowed.status_code == 200
    assert allowed.json() == {
        "store_id": selected_store_id,
        "store_name": "当前门店",
    }

    await _login(client, "member")
    assert (await client.get(f"/api/agent/stores/{selected_store_id}")).status_code == 403

    await _login(client, "outsider")
    inaccessible = await client.get(f"/api/agent/stores/{other_store_id}")
    assert inaccessible.status_code == 403
