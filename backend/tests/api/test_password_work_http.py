"""Password races through public HTTP and an Alembic-migrated SQLite database."""

import asyncio
import threading

import pytest

from app.core import password_work
from tests.api.test_persisted_sessions import login, migrated_clients


@pytest.mark.parametrize("intervention", ["reset", "disable", "delete"])
async def test_paused_login_rejects_changed_account_and_keeps_other_login_working(
    tmp_path, monkeypatch: pytest.MonkeyPatch, intervention: str
) -> None:
    async with migrated_clients(tmp_path) as (_, admin, first, second):
        await login(admin, "session-admin", "AdminPass1")
        created = await admin.post(
            "/api/admin/users", json={"username": "target", "password": "OldPass12"}
        )
        assert created.status_code == 201
        other = await admin.post(
            "/api/admin/users", json={"username": "other", "password": "OtherPass12"}
        )
        assert other.status_code == 201

        entered, release = threading.Event(), threading.Event()
        real_verify = password_work.verify_password

        def paused_verify(password: str, password_hash: str) -> bool:
            if password == "OldPass12":
                entered.set()
                assert release.wait(5)
            return real_verify(password, password_hash)

        monkeypatch.setattr(password_work, "verify_password", paused_verify)
        pending = asyncio.create_task(
            first.post("/api/auth/login", json={"username": "target", "password": "OldPass12"})
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            # This also proves the paused calculation did not block the event loop.
            assert (await second.get("/api/auth/me")).status_code == 401
            assert (
                await second.post(
                    "/api/auth/login", json={"username": "other", "password": "OtherPass12"}
                )
            ).status_code == 200
            user_id = created.json()["id"]
            if intervention == "delete":
                changed = await admin.delete(f"/api/admin/users/{user_id}")
            else:
                changed = await admin.patch(
                    f"/api/admin/users/{user_id}",
                    json={"password": "ResetPass12"}
                    if intervention == "reset"
                    else {"is_active": False},
                )
            assert changed.status_code == (204 if intervention == "delete" else 200)
        finally:
            release.set()
        assert (await pending).status_code == 401
        assert (await first.get("/api/auth/me")).status_code == 401
        assert (await second.get("/api/auth/me")).status_code == 200


@pytest.mark.parametrize("intervention", ["reset", "logout"])
async def test_paused_password_change_rejects_old_password_or_session(
    tmp_path, monkeypatch: pytest.MonkeyPatch, intervention: str
) -> None:
    async with migrated_clients(tmp_path) as (_, admin, first, second):
        await login(admin, "session-admin", "AdminPass1")
        created = await admin.post(
            "/api/admin/users", json={"username": "target", "password": "OldPass12"}
        )
        assert created.status_code == 201
        old_cookie = await login(first, "target", "OldPass12")
        entered, release = threading.Event(), threading.Event()
        real_verify = password_work.verify_password

        def paused_verify(password: str, password_hash: str) -> bool:
            if password == "OldPass12":
                entered.set()
                assert release.wait(5)
            return real_verify(password, password_hash)

        monkeypatch.setattr(password_work, "verify_password", paused_verify)
        pending = asyncio.create_task(
            first.post(
                "/api/auth/password",
                json={"current_password": "OldPass12", "new_password": "NewPass12"},
            )
        )
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            if intervention == "reset":
                changed = await admin.patch(
                    f"/api/admin/users/{created.json()['id']}", json={"password": "ResetPass12"}
                )
                assert changed.status_code == 200
            else:
                changed = await second.post(
                    "/api/auth/logout", headers={"Cookie": f"access_token={old_cookie}"}
                )
                assert changed.status_code == 204
        finally:
            release.set()
        assert (await pending).status_code == 401
        assert (await first.get("/api/auth/me")).status_code == 401
        candidate = "ResetPass12" if intervention == "reset" else "OldPass12"
        assert (
            await second.post("/api/auth/login", json={"username": "target", "password": candidate})
        ).status_code == 200
        assert (
            await admin.post(
                "/api/auth/login", json={"username": "target", "password": "NewPass12"}
            )
        ).status_code == 401


async def test_cancelled_logins_keep_all_four_calculation_slots_until_work_finishes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    async with migrated_clients(tmp_path) as (_, admin, first, second):
        await login(admin, "session-admin", "AdminPass1")
        created = await admin.post(
            "/api/admin/users", json={"username": "target", "password": "OldPass12"}
        )
        assert created.status_code == 201

        release, all_entered = threading.Event(), threading.Event()
        counter_lock = threading.Lock()
        entered = 0
        real_verify = password_work.verify_password

        def paused_verify(password: str, password_hash: str) -> bool:
            nonlocal entered
            with counter_lock:
                entered += 1
                if entered == password_work.PASSWORD_WORK_LIMIT:
                    all_entered.set()
            assert release.wait(5)
            return real_verify(password, password_hash)

        monkeypatch.setattr(password_work, "verify_password", paused_verify)
        requests = [
            asyncio.create_task(
                first.post("/api/auth/login", json={"username": "target", "password": "OldPass12"})
            )
            for _ in range(password_work.PASSWORD_WORK_LIMIT)
        ]
        fifth = None
        try:
            assert await asyncio.to_thread(all_entered.wait, 5)
            for request in requests:
                request.cancel()
            await asyncio.gather(*requests, return_exceptions=True)
            fifth = asyncio.create_task(
                second.post("/api/auth/login", json={"username": "target", "password": "OldPass12"})
            )
            assert (await admin.get("/api/auth/me")).status_code == 200
            with counter_lock:
                assert entered == password_work.PASSWORD_WORK_LIMIT
            assert not fifth.done()
        finally:
            release.set()
        assert fifth is not None
        assert (await fifth).status_code == 200
        with counter_lock:
            assert entered == password_work.PASSWORD_WORK_LIMIT + 1
