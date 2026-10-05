from httpx import AsyncClient
import pytest


@pytest.fixture
async def description_admin(client, user_factory):
    await user_factory(username="description-admin", password="password123", role="admin")
    await client.post("/api/auth/login", json={
        "username": "description-admin", "password": "password123",
    })
    return client


async def test_description_create_read_update_and_clear(client: AsyncClient, user_factory):
    await user_factory(username="description-admin", password="password123", role="admin")
    assert (await client.post("/api/auth/login", json={
        "username": "description-admin", "password": "password123",
    })).status_code == 200
    created = await client.post("/api/admin/stores", json={
        "name": "社区烘焙店", "address": "Roma", "latitude": 41.9, "longitude": 12.5,
        "description": "社区烘焙店\n主营面包与生日蛋糕",
    })
    assert created.status_code == 201
    store = created.json()
    assert store["description"] == "社区烘焙店\n主营面包与生日蛋糕"
    assert store["description_revision"] == 1
    path = f"/api/admin/stores/{store['id']}"
    updated = await client.patch(path, json={
        "description": "  周边居民\n预约蛋糕  ", "expected_description_revision": 1,
    })
    assert updated.status_code == 200
    assert updated.json()["description"] == "  周边居民\n预约蛋糕  "
    assert updated.json()["description_revision"] == 2
    assert (await client.patch(path, json={"name": "新店名"})).json()["description_revision"] == 2
    stale = await client.patch(path, json={
        "name": "不能被保存", "description": "旧草稿", "expected_description_revision": 1,
    })
    assert stale.status_code == 409
    assert stale.json()["detail"]["latest"]["description"] == "  周边居民\n预约蛋糕  "
    assert stale.json()["detail"]["latest"]["description_revision"] == 2
    cleared = await client.patch(path, json={"description": "", "expected_description_revision": 2})
    assert cleared.status_code == 200
    assert cleared.json()["description_revision"] == 3
    listing = (await client.get("/api/admin/stores")).json()
    assert listing[0]["description"] == ""
    assert listing[0]["name"] == "新店名"
    config_path = f"/api/income-config/{store['id']}/current"
    assert (await client.get(config_path)).json()["revision"] == 1
    changed_config = await client.put(f"{path}/income-config", json={
        "enabled": True, "expected_revision": 1,
        "items": [{"name": "现金", "include_in_total": True}],
    })
    assert changed_config.status_code == 200
    assert changed_config.json()["revision"] == 2
    latest_store = (await client.get("/api/admin/stores")).json()[0]
    assert latest_store["description_revision"] == 3


@pytest.mark.parametrize("value, expected", [
    ("", ""), (" \n\t\u3000", ""), ("  零售\n服务  ", "  零售\n服务  "),
    ("字" * 3000, "字" * 3000), ("😀" * 3000, "😀" * 3000),
], ids=["empty", "blank", "multiline", "maximum-chinese", "maximum-emoji"])
async def test_description_text_contract(description_admin, value, expected):
    client = description_admin
    created = await client.post("/api/admin/stores", json={
        "name": "多行业", "address": "Roma", "latitude": 41.9, "longitude": 12.5,
        "description": value,
    })
    assert created.status_code == 201
    assert created.json()["description"] == expected
    saved = await client.patch(f"/api/admin/stores/{created.json()['id']}", json={
        "description": value, "expected_description_revision": 1,
    })
    assert saved.status_code == 200
    assert saved.json()["description"] == expected


@pytest.mark.parametrize("invalid", [None, "字" * 3001, " " * 3001, 123],
                         ids=["null", "too-long", "too-long-blank", "number"])
async def test_invalid_description_does_not_write(description_admin, invalid):
    client = description_admin
    payload = {"name": "多行业", "address": "Roma", "latitude": 41.9, "longitude": 12.5}
    assert (await client.post("/api/admin/stores", json={
        **payload, "description": invalid,
    })).status_code == 422
    store = (await client.post("/api/admin/stores", json=payload)).json()
    assert store["description"] == ""
    assert (await client.patch(f"/api/admin/stores/{store['id']}", json={
        "description": invalid, "expected_description_revision": 1,
    })).status_code == 422
    assert (await client.get("/api/admin/stores")).json()[0]["description_revision"] == 1


@pytest.mark.parametrize("revision", [None, 0, True, "1", 1.5])
async def test_description_requires_a_real_positive_revision(description_admin, revision):
    client = description_admin
    store = (await client.post("/api/admin/stores", json={
        "name": "多行业", "address": "Roma", "latitude": 41.9, "longitude": 12.5,
    })).json()
    assert (await client.patch(f"/api/admin/stores/{store['id']}", json={
        "description": "不能保存", "expected_description_revision": revision,
    })).status_code == 422
    assert (await client.patch(f"/api/admin/stores/{store['id']}", json={
        "description": "缺少版本",
    })).status_code == 422
    assert (await client.get("/api/admin/stores")).json()[0]["description"] == ""


async def test_ordinary_user_cannot_write_either_store(description_admin):
    client = description_admin
    stores = [(await client.post("/api/admin/stores", json={
        "name": name, "address": "Roma", "latitude": 41.9, "longitude": 12.5,
        "description": name,
    })).json() for name in ("烘焙", "维修")]
    assert (await client.post("/api/admin/users", json={
        "username": "description-user", "password": "password123", "store_ids": [stores[0]["id"]],
    })).status_code == 201
    await client.post("/api/auth/login", json={"username": "description-user", "password": "password123"})
    for store in stores:
        assert (await client.patch(f"/api/admin/stores/{store['id']}", json={
            "description": "越权写入", "expected_description_revision": 1,
        })).status_code == 403
    assert (await client.post("/api/admin/stores", json={
        "name": "越权新建", "address": "Roma", "latitude": 41.9, "longitude": 12.5,
        "description": "越权",
    })).status_code == 403
    await client.post("/api/auth/login", json={"username": "description-admin", "password": "password123"})
    listing = (await client.get("/api/admin/stores")).json()
    assert {item["description"] for item in listing} == {"烘焙", "维修"}
