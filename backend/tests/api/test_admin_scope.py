from datetime import datetime, timezone

import pytest

from app.models.identity import StoreMember


async def test_creator_controls_employee_editors_without_delegating_grant_authority(
    client, db_session, primary_admin_factory, user_factory, store_factory
):
    await primary_admin_factory(username="primary", password="password123", role="admin")
    creator = await user_factory(username="creator", password="password123", role="admin")
    editor = await user_factory(username="editor", password="password123", role="admin")
    hidden_editor = await user_factory(username="outsider", password="password123", role="admin")
    shared = await store_factory(name="Shared")
    private = await store_factory(name="Private")
    creator_id, editor_id, outsider_id = creator.id, editor.id, hidden_editor.id
    shared_id, private_id = shared.id, private.id
    db_session.add_all(
        [
            StoreMember(user_id=creator_id, store_id=shared_id),
            StoreMember(user_id=creator_id, store_id=private_id),
            StoreMember(user_id=editor_id, store_id=shared_id),
        ]
    )
    await db_session.commit()

    async def login(username):
        assert (
            await client.post(
                "/api/auth/login", json={"username": username, "password": "password123"}
            )
        ).status_code == 200

    await login("creator")
    created = await client.post(
        "/api/admin/users",
        json={
            "username": "delegated-employee",
            "password": "password123",
            "store_ids": [shared_id, private_id],
            "editor_ids": [editor_id],
        },
    )
    assert created.status_code == 201
    employee_id = created.json()["id"]
    assert created.json()["creator_id"] == creator_id
    assert created.json()["editor_ids"] == [editor_id]
    await login("editor")
    listed = (await client.get("/api/admin/users")).json()
    assert [user["id"] for user in listed] == [employee_id]
    assert listed[0]["store_ids"] == [shared_id]
    assert listed[0]["can_manage_editors"] is False
    assert (
        await client.patch(f"/api/admin/users/{employee_id}", json={"role": "admin"})
    ).status_code == 403
    assert (
        await client.patch(f"/api/admin/users/{employee_id}", json={"manager_id": editor_id})
    ).status_code == 403
    assert (
        await client.patch(f"/api/admin/users/{employee_id}", json={"editor_ids": [outsider_id]})
    ).status_code == 403
    assert (
        await client.patch(f"/api/admin/users/{employee_id}", json={"store_ids": [private_id]})
    ).status_code == 403
    assert (
        await client.patch(
            f"/api/admin/users/{employee_id}", json={"password": "changed123", "store_ids": []}
        )
    ).status_code == 200
    await login("creator")
    assert [
        store["id"] for store in (await client.get(f"/api/admin/users/{employee_id}/stores")).json()
    ] == [private_id]
    assert (
        await client.patch(f"/api/admin/users/{employee_id}", json={"editor_ids": []})
    ).status_code == 200
    await login("editor")
    assert (await client.get("/api/admin/users")).json() == []
    assert (
        await client.patch(f"/api/admin/users/{employee_id}", json={"is_active": False})
    ).status_code == 403


async def test_primary_always_manages_employees_and_requires_explicit_manager(
    client, db_session, primary_admin_factory, monkeypatch
):
    primary = await primary_admin_factory(username="primary", password="password123", role="user")
    # primary_admin_factory configures raw admin actors; configure this historical raw user explicitly.
    from app.core.config import get_settings

    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", primary.username)
    get_settings.cache_clear()
    primary_id = primary.id
    await db_session.commit()
    await client.post("/api/auth/login", json={"username": "primary", "password": "password123"})
    body = {"username": "employee", "password": "password123"}
    assert (await client.post("/api/admin/users", json=body)).status_code == 422
    created = await client.post("/api/admin/users", json=body | {"manager_id": primary_id})
    assert created.status_code == 201
    ident = created.json()["id"]
    assert (
        await client.patch(f"/api/admin/users/{ident}", json={"manager_id": None})
    ).status_code == 422
    assert (
        await client.patch(f"/api/admin/users/{ident}", json={"editor_ids": [primary_id]})
    ).status_code == 422
    assert (
        await client.patch(f"/api/admin/users/{ident}", json={"editor_ids": [], "is_active": False})
    ).status_code == 200


async def test_employee_update_and_transfer_retain_existing_archived_scope(
    client, db_session, primary_admin_factory, user_factory, store_factory
):
    primary = await primary_admin_factory(username="primary", password="password123", role="admin")
    manager = await user_factory(username="manager", password="password123", role="admin")
    employee = await user_factory(
        username="employee", password="password123", manager_id=primary.id
    )
    archived = await store_factory(name="Archived", is_active=False)
    new_archived = await store_factory(name="Unassigned archive", is_active=False)
    employee_id, manager_id, archived_id, new_id = (
        employee.id,
        manager.id,
        archived.id,
        new_archived.id,
    )
    db_session.add_all(
        [
            StoreMember(user_id=manager_id, store_id=archived_id),
            StoreMember(user_id=manager_id, store_id=new_id),
            StoreMember(user_id=employee_id, store_id=archived_id),
        ]
    )
    await db_session.commit()
    await client.post("/api/auth/login", json={"username": "primary", "password": "password123"})
    moved = await client.patch(f"/api/admin/users/{employee_id}", json={"manager_id": manager_id})
    assert moved.status_code == 200, moved.text
    assert moved.json()["store_ids"] == [archived_id]
    await client.post("/api/auth/login", json={"username": "manager", "password": "password123"})
    kept = await client.patch(f"/api/admin/users/{employee_id}", json={"store_ids": [archived_id]})
    assert kept.status_code == 200, kept.text
    assert (
        await client.patch(
            f"/api/admin/users/{employee_id}", json={"store_ids": [archived_id, new_id]}
        )
    ).status_code == 409


async def test_business_exports_configuration_logs_and_archived_scope_are_isolated(
    client, db_session, user_factory, store_factory
):
    from app.models.ledger import IncomeCategory
    from app.models.operations import ScheduledTaskLog, SystemAlert

    admin = await user_factory(username="scoped-admin", password="password123", role="admin")
    allowed = await store_factory(name="Archived allowed", is_active=False)
    hidden = await store_factory(name="Hidden")
    allowed_id, hidden_id = allowed.id, hidden.id
    category = IncomeCategory(store_id=hidden_id, name="Hidden category", include_in_total=True)
    db_session.add_all([category, StoreMember(user_id=admin.id, store_id=allowed_id)])
    for store_id in (allowed_id, hidden_id, None):
        db_session.add(
            SystemAlert(
                store_id=store_id, alert_type="test", level="warning", message="Scoped message"
            )
        )
        db_session.add(
            ScheduledTaskLog(
                store_id=store_id,
                task_type="test",
                status="success",
                message="Scoped log",
                started_at=datetime.now(timezone.utc),
            )
        )
    await db_session.commit()
    await client.post(
        "/api/auth/login", json={"username": "scoped-admin", "password": "password123"}
    )
    assert [s["id"] for s in (await client.get("/api/admin/stores")).json()] == [allowed_id]
    for path in (
        f"/api/ledger/{hidden_id}/2026-09-01",
        f"/api/database/{hidden_id}",
        f"/api/database/{hidden_id}/export.xlsx",
        f"/api/charts/{hidden_id}?start=2026-09-01&end=2026-09-30",
        f"/api/settlements/{hidden_id}",
        f"/api/admin/stores/{hidden_id}/income-config",
        f"/api/admin/income-categories?store_id={hidden_id}",
        f"/api/agent/{hidden_id}/conversation",
        f"/api/agent/{hidden_id}/memories",
        f"/api/agent/{hidden_id}/memory-jobs",
    ):
        response = await client.get(path)
        assert response.status_code == 404, (path, response.text)
    for path in ("/api/admin/alerts", "/api/admin/task-logs"):
        assert [row["store_id"] for row in (await client.get(path)).json()] == [allowed_id]
    assert (await client.get("/api/admin/diagnostics")).status_code == 403


async def test_manager_inactivity_does_not_disable_employee_and_raw_user_primary_can_demote_last_admin(
    client, db_session, user_factory, store_factory, monkeypatch
):
    from app.core.config import get_settings

    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "primary")
    get_settings.cache_clear()
    primary = await user_factory(username="primary", password="password123", role="user")
    admin = await user_factory(username="manager", password="password123", role="admin")
    employee = await user_factory(username="employee", password="password123", manager_id=admin.id)
    store = await store_factory(name="Effective")
    admin_id, employee_id, primary_id, store_id = admin.id, employee.id, primary.id, store.id
    db_session.add_all(
        [
            StoreMember(user_id=admin_id, store_id=store_id),
            StoreMember(user_id=employee_id, store_id=store_id),
        ]
    )
    await db_session.commit()
    await client.post("/api/auth/login", json={"username": "primary", "password": "password123"})
    assert (
        await client.patch(f"/api/admin/users/{admin_id}", json={"is_active": False})
    ).status_code == 200
    await client.post("/api/auth/login", json={"username": "employee", "password": "password123"})
    assert [s["id"] for s in (await client.get("/api/stores/accessible")).json()] == [store_id]
    await client.post("/api/auth/login", json={"username": "primary", "password": "password123"})
    assert (await client.delete(f"/api/admin/users/{admin_id}")).status_code == 409
    assert (
        await client.patch(f"/api/admin/users/{admin_id}", json={"role": "user"})
    ).status_code == 409
    assert (
        await client.patch(f"/api/admin/users/{employee_id}", json={"manager_id": primary_id})
    ).status_code == 200
    assert (
        await client.patch(f"/api/admin/users/{admin_id}", json={"role": "user"})
    ).status_code == 200


@pytest.mark.asyncio
async def test_subadministrator_has_only_explicit_store_access(
    client, db_session, user_factory, store_factory
):
    admin = await user_factory(username="limited-admin", password="password123", role="admin")
    allowed = await store_factory(name="Allowed")
    hidden = await store_factory(name="Hidden")
    db_session.add(StoreMember(user_id=admin.id, store_id=allowed.id))
    await db_session.flush()
    assert (
        await client.post(
            "/api/auth/login", json={"username": admin.username, "password": "password123"}
        )
    ).status_code == 200
    response = await client.get("/api/admin/stores")
    assert [store["id"] for store in response.json()] == [allowed.id]
    assert (await client.get(f"/api/admin/stores/{hidden.id}/members")).status_code == 404
    assert (
        await client.post(
            "/api/admin/stores",
            json={"name": "Forbidden", "address": "Test", "latitude": 45, "longitude": 9},
        )
    ).status_code == 403


async def test_employee_creation_is_owned_and_cannot_expand_scope(
    client, db_session, user_factory, store_factory
):
    admin = await user_factory(username="manager-one", password="password123", role="admin")
    allowed = await store_factory(name="Allowed")
    hidden = await store_factory(name="Hidden")
    db_session.add(StoreMember(user_id=admin.id, store_id=allowed.id))
    await db_session.commit()
    await client.post(
        "/api/auth/login", json={"username": admin.username, "password": "password123"}
    )
    response = await client.post(
        "/api/admin/users",
        json={"username": "owned-employee", "password": "password123", "store_ids": [allowed.id]},
    )
    assert response.status_code == 201
    assert response.json()["manager_id"] == admin.id
    employee_id = response.json()["id"]
    response = await client.patch(
        f"/api/admin/users/{employee_id}", json={"store_ids": [hidden.id]}
    )
    assert response.status_code == 403
    assert (await client.get(f"/api/admin/users/{employee_id}/stores")).json()[0][
        "id"
    ] == allowed.id
    other = await user_factory(username="manager-two", password="password123", role="admin")
    await db_session.commit()
    await client.post(
        "/api/auth/login", json={"username": other.username, "password": "password123"}
    )
    assert (await client.get("/api/admin/users")).json() == []
    assert (
        await client.patch(f"/api/admin/users/{employee_id}", json={"password": "changed123"})
    ).status_code == 403


async def test_revocation_removes_employee_scope_without_restoring_it_on_regrant(
    client, db_session, user_factory, store_factory, monkeypatch
):
    from app.core.config import get_settings

    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "owner")
    get_settings.cache_clear()
    await user_factory(username="owner", password="password123", role="admin")
    admin = await user_factory(username="limited", password="password123", role="admin")
    store = await store_factory(name="Shared")
    store_id = store.id
    admin_id = admin.id
    db_session.add(StoreMember(user_id=admin.id, store_id=store.id))
    await db_session.commit()
    await client.post("/api/auth/login", json={"username": "limited", "password": "password123"})
    employee = (
        await client.post(
            "/api/admin/users",
            json={"username": "employee", "password": "password123", "store_ids": [store.id]},
        )
    ).json()
    await client.post("/api/auth/login", json={"username": "owner", "password": "password123"})
    response = await client.patch(f"/api/admin/users/{admin.id}", json={"store_ids": []})
    assert response.status_code == 200
    assert (await client.get(f"/api/admin/users/{employee['id']}/stores")).json() == []
    response = await client.patch(f"/api/admin/users/{admin_id}", json={"store_ids": [store_id]})
    assert response.status_code == 200
    await client.post("/api/auth/login", json={"username": "employee", "password": "password123"})
    assert (await client.get("/api/stores/accessible")).json() == []


async def test_transfer_and_member_edit_preserve_other_administrators_scope(
    client, db_session, user_factory, store_factory, monkeypatch
):
    from app.core.config import get_settings

    monkeypatch.setenv("AUTOLAVA_BOOTSTRAP_USERNAME", "primary")
    get_settings.cache_clear()
    await user_factory(username="primary", password="password123", role="admin")
    first = await user_factory(username="first-admin", password="password123", role="admin")
    second = await user_factory(username="second-admin", password="password123", role="admin")
    shared = await store_factory(name="Shared")
    exclusive = await store_factory(name="Exclusive")
    first_id, second_id, shared_id, exclusive_id = first.id, second.id, shared.id, exclusive.id
    db_session.add_all(
        [
            StoreMember(user_id=first_id, store_id=shared_id),
            StoreMember(user_id=first_id, store_id=exclusive_id),
            StoreMember(user_id=second_id, store_id=shared_id),
        ]
    )
    await db_session.commit()
    await client.post(
        "/api/auth/login", json={"username": "first-admin", "password": "password123"}
    )
    employee = (
        await client.post(
            "/api/admin/users",
            json={
                "username": "transfer-employee",
                "password": "password123",
                "store_ids": [shared_id, exclusive_id],
            },
        )
    ).json()
    assert (
        await client.put(f"/api/admin/stores/{shared_id}/members", json={"user_ids": [second_id]})
    ).status_code == 403
    await client.post("/api/auth/login", json={"username": "primary", "password": "password123"})
    moved = await client.patch(f"/api/admin/users/{employee['id']}", json={"manager_id": second_id})
    assert moved.status_code == 200
    assert moved.json()["store_ids"] == [shared_id]
    assert moved.json()["id"] == employee["id"]
    await client.post(
        "/api/auth/login", json={"username": "first-admin", "password": "password123"}
    )
    assert (
        await client.patch(f"/api/admin/users/{employee['id']}", json={"manager_id": first_id})
    ).status_code == 403
    third = await user_factory(username="third-admin", password="password123", role="admin")
    db_session.add(StoreMember(user_id=third.id, store_id=shared_id))
    await db_session.commit()
    await client.post(
        "/api/auth/login", json={"username": "third-admin", "password": "password123"}
    )
    assert (
        await client.put(f"/api/admin/stores/{shared_id}/members", json={"user_ids": []})
    ).status_code == 200
    await client.post(
        "/api/auth/login", json={"username": "transfer-employee", "password": "password123"}
    )
    assert [item["id"] for item in (await client.get("/api/stores/accessible")).json()] == [
        shared_id
    ]
    assert (await client.get("/api/admin/stores")).status_code == 403
    assert (await client.get(f"/api/agent/{shared_id}/conversation")).status_code == 403
