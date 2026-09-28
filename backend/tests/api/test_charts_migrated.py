"""Exercise analysis through public APIs on a disposable migrated database."""

import os
import subprocess
import sys
from decimal import Decimal
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session, sqlite_url
from app.core.security import hash_password
from app.main import create_app
from app.models.identity import Store, StoreMember, User


class NoWeather:
    async def get_daily(self, store, target):
        return None


async def test_migrated_analysis_sample_and_setting_round_trip(tmp_path: Path) -> None:
    database = tmp_path / "analysis.sqlite3"
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=Path(__file__).parents[2],
        env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(database)},
        check=True,
        capture_output=True,
    )
    engine = create_async_engine(sqlite_url(database))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with factory() as setup:
            user = User(
                username="analysis-admin", password_hash=hash_password("AdminPass1"), role="admin"
            )
            store = Store(
                name="Migrated analysis",
                address="Address",
                latitude=Decimal("45"),
                longitude=Decimal("9"),
                timezone="Europe/Rome",
                is_active=True,
            )
            setup.add_all([user, store])
            await setup.flush()
            setup.add(StoreMember(store_id=store.id, user_id=user.id))
            store_id = store.id
            await setup.commit()

        app = create_app()
        app.state.weather_service = NoWeather()

        async def override_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_session] = override_session
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://testserver"
        ) as client:
            login = await client.post(
                "/api/auth/login", json={"username": "analysis-admin", "password": "AdminPass1"}
            )
            assert login.status_code == 200
            for day, revenue, count in (("12", 150, 3), ("13", 50, None)):
                saved = await client.put(
                    f"/api/ledger/{store_id}/2026-07-{day}",
                    json={
                        "is_open": "营业",
                        "daily_revenue": revenue,
                        "wash_count": count,
                        "items": [],
                    },
                )
                assert saved.status_code == 201, saved.text

            async def kpis():
                result = await client.get(f"/api/charts/{store_id}?start=2026-07-12&end=2026-07-13")
                assert result.status_code == 200, result.text
                return result.json()["kpis"]

            before = await kpis()
            assert (
                before["average_ticket"],
                before["wash_count_covered_days"],
                before["open_days"],
                before["wash_count_coverage_status"],
            ) == (50, 1, 2, "partial")
            disabled = await client.patch(
                f"/api/admin/stores/{store_id}", json={"wash_count_enabled": False}
            )
            assert disabled.status_code == 200, disabled.text
            hidden = await kpis()
            assert hidden["total_wash_count"] is None
            assert hidden["average_ticket"] is None
            assert hidden["wash_count_covered_days"] is None
            assert hidden["wash_count_coverage_status"] is None
            enabled = await client.patch(
                f"/api/admin/stores/{store_id}", json={"wash_count_enabled": True}
            )
            assert enabled.status_code == 200, enabled.text
            assert (await kpis())["average_ticket"] == 50

            for day, state, count in (("14", "营业", 0), ("15", "营业", None), ("16", "休息", 0)):
                saved = await client.put(
                    f"/api/ledger/{store_id}/2026-07-{day}",
                    json={"is_open": state, "daily_revenue": 0, "wash_count": count, "items": []},
                )
                assert saved.status_code == 201, saved.text
            for day, expected in (
                ("14", (0, 1, "complete", None)),
                ("15", (None, 0, "missing", None)),
                ("16", (None, 0, "no_operating_days", None)),
            ):
                result = await client.get(
                    f"/api/charts/{store_id}?start=2026-07-{day}&end=2026-07-{day}"
                )
                assert result.status_code == 200, result.text
                observed = result.json()["kpis"]
                assert (
                    observed["total_wash_count"],
                    observed["wash_count_covered_days"],
                    observed["wash_count_coverage_status"],
                    observed["average_ticket"],
                ) == expected
    finally:
        await engine.dispose()
