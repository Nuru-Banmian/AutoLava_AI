from datetime import date

import pytest


@pytest.mark.anyio
async def test_old_config_and_ledger_draft_cannot_write_after_config_changes(
    client, primary_admin_factory, store_factory, db_session
):
    await primary_admin_factory(username="revision-admin", password="secret123", role="admin")
    assert (await client.post("/api/auth/login", json={"username": "revision-admin", "password": "secret123"})).status_code == 200
    store = await store_factory(name="Revision store")
    await db_session.commit()
    url = f"/api/income-config/{store.id}/current"
    first = (await client.get(url)).json()
    assert first["revision"] == 1
    publish_url = f"/api/admin/stores/{store.id}/income-config"
    published = await client.put(publish_url, json={"expected_revision": first["revision"], "enabled": False, "items": []})
    assert published.status_code == 200
    assert published.json()["revision"] == 2
    stale = await client.put(publish_url, json={"expected_revision": 1, "enabled": True, "items": []})
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "income_config_revision_conflict"
    assert (await client.get(url)).json()["enabled"] is False
    ledger = await client.put(f"/api/ledger/{store.id}/{date(2026, 7, 1)}", json={
        "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
        "is_open": "营业", "daily_revenue": 25, "items": [],
    })
    assert ledger.status_code == 409
    assert ledger.json()["detail"]["code"] == "income_config_revision_conflict"
    assert ledger.json()["detail"]["current_record"] is None


@pytest.mark.anyio
async def test_each_category_entry_advances_one_shared_revision(
    client, primary_admin_factory, store_factory, db_session
):
    await primary_admin_factory(username="category-admin", password="secret123", role="admin")
    assert (await client.post("/api/auth/login", json={"username": "category-admin", "password": "secret123"})).status_code == 200
    store = await store_factory(name="Category revision store")
    await db_session.commit()
    config_url = f"/api/income-config/{store.id}/current"

    async def revision():
        return (await client.get(config_url)).json()["revision"]

    created = await client.post("/api/admin/income-categories", json={
        "store_id": store.id, "name": "Cash", "include_in_total": True,
        "expected_revision": 1,
    })
    assert created.status_code == 201
    category_id = created.json()["id"]
    assert await revision() == 2

    patch_url = f"/api/admin/income-categories/{category_id}"
    stale = await client.patch(patch_url, json={"name": "Wrong", "expected_revision": 1})
    assert stale.status_code == 409
    assert stale.json()["detail"]["current_config"]["revision"] == 2
    assert await revision() == 2
    patched = await client.patch(patch_url, json={
        "name": "Renamed", "sort_order": 5, "include_in_total": False,
        "is_active": False, "expected_revision": 2,
    })
    assert patched.status_code == 200
    assert await revision() == 3
    archived = await client.post(f"{patch_url}/archive", json={"expected_revision": 3})
    assert archived.status_code == 200
    assert await revision() == 4
    restored = await client.post(f"{patch_url}/restore", json={"expected_revision": 4})
    assert restored.status_code == 200
    assert await revision() == 5
    removed = await client.request("DELETE", patch_url, json={"expected_revision": 5})
    assert removed.status_code == 204
    assert await revision() == 6


@pytest.mark.anyio
async def test_missing_revision_requires_reload_without_mutation(
    client, primary_admin_factory, store_factory, db_session
):
    await primary_admin_factory(username="missing-admin", password="secret123", role="admin")
    assert (await client.post("/api/auth/login", json={"username": "missing-admin", "password": "secret123"})).status_code == 200
    store = await store_factory(name="Missing revision store")
    await db_session.commit()
    store_id = store.id
    published = await client.put(f"/api/admin/stores/{store_id}/income-config", json={
        "enabled": True, "items": [{"name": "Cash", "include_in_total": True}],
    })
    assert published.status_code == 428
    recorded = await client.put(f"/api/ledger/{store_id}/2026-07-01", json={
        "expected_identity": None, "expected_revision": None,
        "is_open": "营业", "daily_revenue": 20, "items": [],
    })
    assert recorded.status_code == 428
    current = (await client.get(f"/api/income-config/{store_id}/current")).json()
    assert current["revision"] == 1
    assert current["items"] == []


@pytest.mark.anyio
async def test_config_conflict_preserves_existing_record_and_category_snapshot(
    client, primary_admin_factory, store_factory, db_session
):
    await primary_admin_factory(username="snapshot-admin", password="secret123", role="admin")
    assert (await client.post("/api/auth/login", json={"username": "snapshot-admin", "password": "secret123"})).status_code == 200
    store = await store_factory(name="Snapshot revision store")
    store_id = store.id
    await db_session.commit()
    config_path = f"/api/admin/stores/{store_id}/income-config"
    first = await client.put(config_path, json={
        "expected_revision": 1, "enabled": True,
        "items": [{"name": "Cash", "include_in_total": True}],
    })
    assert first.status_code == 200
    category_id = first.json()["items"][0]["id"]
    ledger_path = f"/api/ledger/{store_id}/2026-07-01"
    created = await client.put(ledger_path, json={
        "expected_identity": None, "expected_revision": None, "expected_config_revision": 2,
        "is_open": "营业", "items": [{"category_id": category_id, "amount": 50}],
    })
    assert created.status_code == 201
    record = (await client.get(ledger_path)).json()
    changed = await client.patch(f"/api/admin/income-categories/{category_id}", json={
        "expected_revision": 2, "name": "Renamed", "include_in_total": False,
    })
    assert changed.status_code == 200
    stale = await client.put(ledger_path, json={
        "expected_identity": record["identity"], "expected_revision": record["revision"],
        "expected_config_revision": 2, "is_open": "营业",
        "items": [{"category_id": category_id, "amount": 99}],
    })
    assert stale.status_code == 409
    detail = stale.json()["detail"]
    assert detail["code"] == "income_config_revision_conflict"
    assert detail["current_config"]["revision"] == 3
    assert detail["current_record"]["daily_revenue"] == 50
    after = (await client.get(ledger_path)).json()
    assert after["revision"] == record["revision"]
    assert after["daily_revenue"] == 50
    assert after["items"][0]["category_name"] == "Cash"
    assert after["items"][0]["include_in_total"] is True
