import asyncio
from datetime import datetime, timedelta
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
from secrets import token_hex
from zoneinfo import ZoneInfo

import bcrypt
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import get_session, sqlite_url
from app.main import create_app
from app.services.briefing import BriefingService
from app.services.weather import WeatherResult


async def test_historical_weather_resumes_after_process_restart(
    tmp_path: Path, monkeypatch
) -> None:
    database_path = tmp_path / "ledger.sqlite3"
    backend = Path(__file__).parents[2]
    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=backend,
        env=os.environ | {"AUTOLAVA_DATABASE_PATH": str(database_path)},
        check=True,
        capture_output=True,
    )
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            "INSERT INTO users (auth_identity, username, password_hash, role, is_active) VALUES (?, ?, ?, 'admin', 1)",
            (token_hex(32), "weather-admin", bcrypt.hashpw(b"secret", bcrypt.gensalt()).decode()),
        )
        connection.execute(
            "INSERT INTO stores (name, address, latitude, longitude, timezone, is_active, income_items_enabled) VALUES ('Weather', 'Address', 45, 9, 'Europe/Rome', 1, 0)"
        )
        connection.execute("INSERT INTO store_members (store_id, user_id) VALUES (1, 1)")
        connection.commit()

    engine = create_async_engine(sqlite_url(database_path))
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    entered = asyncio.Event()
    release = asyncio.Event()

    class BlockedWeather:
        async def get_daily(self, store, target):
            entered.set()
            await release.wait()
            return WeatherResult("晴", 0, 20.0, 10.0, 0.0)

    class AvailableWeather:
        async def get_daily(self, store, target):
            return WeatherResult("晴", 0, 20.0, 10.0, 0.0)

    def build_app(weather):
        app = create_app(session_factory=sessions, weather_service=weather)

        async def migrated_session():
            async with sessions() as session:
                yield session

        app.dependency_overrides[get_session] = migrated_session
        return app

    path = "/api/ledger/1/2020-01-15"
    first_app = build_app(BlockedWeather())
    async with first_app.router.lifespan_context(first_app):
        network_client = first_app.state.open_meteo_provider.client
        assert network_client is not None
        await first_app.state.background_refresh_scheduler.stop()
        async with AsyncClient(
            transport=ASGITransport(app=first_app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "weather-admin", "password": "secret"}
                )
            ).status_code == 200
            form_response = await client.get(f"{path}/form-config")
            assert form_response.status_code == 200, form_response.text
            form = form_response.json()
            response = await asyncio.wait_for(
                client.put(
                    path,
                    json={
                        "expected_identity": None,
                        "expected_revision": None,
                        "expected_config_revision": form["config_revision"],
                        "is_open": "营业",
                        "daily_revenue": 125,
                        "weather": None,
                        "weather_edited": False,
                        "items": [],
                    },
                ),
                timeout=2,
            )
            assert response.status_code == 201
            assert (await client.get(path)).json()["daily_revenue"] == 125
            await asyncio.wait_for(entered.wait(), timeout=2)
    assert network_client.is_closed
    release.set()

    second_app = build_app(AvailableWeather())
    async with second_app.router.lifespan_context(second_app):
        await second_app.state.background_refresh_scheduler.stop()
        async with AsyncClient(
            transport=ASGITransport(app=second_app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "weather-admin", "password": "secret"}
                )
            ).status_code == 200

            async def refreshed():
                while True:
                    record = (await client.get(path)).json()
                    if record["weather_auto"] == "晴":
                        return record
                    await asyncio.sleep(0)

            record = await asyncio.wait_for(refreshed(), timeout=3)
            assert record["weather"] == "晴"
            assert record["daily_revenue"] == 125
            card = (
                await client.get(
                    "/api/database/1/records", params={"start": "2020-01-15", "end": "2020-01-15"}
                )
            ).json()["items"][0]
            assert [event["action"] for event in card["bookkeeping_events"]] == ["created"]

    entered.clear()
    release.clear()
    third_app = build_app(BlockedWeather())
    async with third_app.router.lifespan_context(third_app):
        await third_app.state.background_refresh_scheduler.stop()
        async with AsyncClient(
            transport=ASGITransport(app=third_app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "weather-admin", "password": "secret"}
                )
            ).status_code == 200
            update_body = {
                "expected_identity": record["identity"],
                "expected_revision": record["revision"],
                "expected_config_revision": record["config_revision"],
                "is_open": "营业",
                "daily_revenue": 125,
                "weather": "晴",
                "weather_edited": False,
                "items": [],
            }
            assert (await client.put(path, json=update_body)).status_code == 200
            await asyncio.wait_for(entered.wait(), timeout=2)
            current = (await client.get(path)).json()
            clear = await client.put(
                path,
                json=update_body
                | {
                    "expected_revision": current["revision"],
                    "weather": None,
                    "weather_edited": True,
                },
            )
            assert clear.status_code == 200
            release.set()

            async def skipped():
                while True:
                    logs = (await client.get("/api/admin/task-logs")).json()
                    if any(
                        log["task_type"] == "ledger_weather_refresh" and log["status"] == "skipped"
                        for log in logs
                    ):
                        return
                    await asyncio.sleep(0)

            await asyncio.wait_for(skipped(), timeout=3)
            after_clear = (await client.get(path)).json()
            assert after_clear["weather"] is None
            assert after_clear["weather_edited"] is True
            assert after_clear["daily_revenue"] == 125

    entered.clear()
    release.clear()
    fourth_app = build_app(BlockedWeather())
    async with fourth_app.router.lifespan_context(fourth_app):
        await fourth_app.state.background_refresh_scheduler.stop()
        async with AsyncClient(
            transport=ASGITransport(app=fourth_app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "weather-admin", "password": "secret"}
                )
            ).status_code == 200
            current = (await client.get(path)).json()
            assert (
                await client.request(
                    "DELETE",
                    path,
                    json={
                        "expected_identity": current["identity"],
                        "expected_revision": current["revision"],
                    },
                )
            ).status_code == 204
            fresh_body = {
                "expected_identity": None,
                "expected_revision": None,
                "expected_config_revision": current["config_revision"],
                "is_open": "营业",
                "daily_revenue": 220,
                "weather": None,
                "weather_edited": False,
                "items": [],
            }
            assert (await client.put(path, json=fresh_body)).status_code == 201
            await asyncio.wait_for(entered.wait(), timeout=2)
            old_record = (await client.get(path)).json()
            previous_logs = (await client.get("/api/admin/task-logs")).json()
            last_log_id = max((log["id"] for log in previous_logs), default=0)
            assert (
                await client.request(
                    "DELETE",
                    path,
                    json={
                        "expected_identity": old_record["identity"],
                        "expected_revision": old_record["revision"],
                    },
                )
            ).status_code == 204
            assert (
                await client.put(
                    path,
                    json=fresh_body
                    | {
                        "daily_revenue": 330,
                        "weather": "小雨",
                        "weather_edited": True,
                    },
                )
            ).status_code == 201
            release.set()

            async def old_result_skipped():
                while True:
                    logs = (await client.get("/api/admin/task-logs")).json()
                    if any(
                        log["id"] > last_log_id
                        and log["task_type"] == "ledger_weather_refresh"
                        and log["status"] == "skipped"
                        for log in logs
                    ):
                        return
                    await asyncio.sleep(0)

            await asyncio.wait_for(old_result_skipped(), timeout=3)
            replacement = (await client.get(path)).json()
            assert replacement["identity"] != old_record["identity"]
            assert replacement["weather"] == "小雨"
            assert replacement["daily_revenue"] == 330

    class NoWeather:
        def __init__(self):
            self.calls = 0

        async def get_daily(self, store, target):
            self.calls += 1
            raise AssertionError("Manual weather does not need a provider")

    no_weather = NoWeather()
    fifth_app = build_app(no_weather)
    async with fifth_app.router.lifespan_context(fifth_app):
        await fifth_app.state.background_refresh_scheduler.stop()
        async with AsyncClient(
            transport=ASGITransport(app=fifth_app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "weather-admin", "password": "secret"}
                )
            ).status_code == 200
            today = datetime.now(ZoneInfo("Europe/Rome")).date().isoformat()
            today_path = f"/api/ledger/1/{today}"
            assert (
                await client.put(
                    today_path,
                    json=fresh_body
                    | {
                        "daily_revenue": 440,
                        "weather": "多云",
                        "weather_edited": True,
                    },
                )
            ).status_code == 201

            async def current_briefing():
                while True:
                    cards = (await client.get("/api/dashboard/1")).json()
                    if any(
                        card["card_type"] == "today"
                        and card["revenue"] == 440
                        and card["weather"] == "多云"
                        for card in cards
                    ):
                        return
                    await asyncio.sleep(0)

            await asyncio.wait_for(current_briefing(), timeout=3)
            assert no_weather.calls == 0

    historical_path = "/api/ledger/1/2020-01-17"
    historical_app = build_app(AvailableWeather())
    async with historical_app.router.lifespan_context(historical_app):
        await historical_app.state.background_refresh_scheduler.stop()
        async with AsyncClient(
            transport=ASGITransport(app=historical_app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "weather-admin", "password": "secret"}
                )
            ).status_code == 200
            assert (
                await client.put(
                    historical_path,
                    json=fresh_body
                    | {"daily_revenue": 300, "weather": None, "weather_edited": False},
                )
            ).status_code == 201

            async def historical_weather():
                while True:
                    item = (await client.get(historical_path)).json()
                    if item["weather_auto"] == "晴":
                        return item
                    await asyncio.sleep(0)

            historical_snapshot = await asyncio.wait_for(historical_weather(), timeout=3)

    location_entered = asyncio.Event()
    location_release = asyncio.Event()

    class LocationWeather:
        async def get_daily(self, store, target):
            if float(store.latitude) == 45:
                location_entered.set()
                await location_release.wait()
                return WeatherResult("晴", 0, 20.0, 10.0, 0.0)
            return WeatherResult("小雨", 61, 18.0, 9.0, 2.0)

    sixth_app = build_app(LocationWeather())
    async with sixth_app.router.lifespan_context(sixth_app):
        await sixth_app.state.background_refresh_scheduler.stop()
        async with AsyncClient(
            transport=ASGITransport(app=sixth_app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "weather-admin", "password": "secret"}
                )
            ).status_code == 200
            location_path = "/api/ledger/1/2020-01-16"
            assert (
                await client.put(
                    location_path,
                    json=fresh_body
                    | {
                        "daily_revenue": 550,
                        "weather": None,
                        "weather_edited": False,
                    },
                )
            ).status_code == 201
            await asyncio.wait_for(location_entered.wait(), timeout=2)
            assert (
                await client.patch("/api/admin/stores/1", json={"latitude": 46})
            ).status_code == 200
            location_release.set()

            async def new_location_applied():
                while True:
                    current = (await client.get(location_path)).json()
                    if current["weather_auto"] == "小雨":
                        return current
                    await asyncio.sleep(0)

            after_move = await asyncio.wait_for(new_location_applied(), timeout=3)
            assert after_move["weather"] == "小雨"
            assert after_move["daily_revenue"] == 550
            unchanged_history = (await client.get(historical_path)).json()
            assert unchanged_history["weather_auto"] == "晴"
            assert unchanged_history["revision"] == historical_snapshot["revision"]

    briefing_interrupted = asyncio.Event()
    interrupted_date = (
        datetime.now(ZoneInfo("Europe/Rome")).date() - timedelta(days=1)
    ).isoformat()
    interrupted_path = f"/api/ledger/1/{interrupted_date}"

    async def interrupt_briefing(*args, **kwargs):
        briefing_interrupted.set()
        raise asyncio.CancelledError

    with monkeypatch.context() as patch:
        patch.setattr(BriefingService, "regenerate", interrupt_briefing)
        interrupted_app = build_app(AvailableWeather())
        async with interrupted_app.router.lifespan_context(interrupted_app):
            await interrupted_app.state.background_refresh_scheduler.stop()
            async with AsyncClient(
                transport=ASGITransport(app=interrupted_app), base_url="http://testserver"
            ) as client:
                assert (
                    await client.post(
                        "/api/auth/login",
                        json={"username": "weather-admin", "password": "secret"},
                    )
                ).status_code == 200
                assert (
                    await client.put(
                        interrupted_path,
                        json=fresh_body
                        | {
                            "daily_revenue": 441,
                            "weather": None,
                            "weather_edited": False,
                        },
                    )
                ).status_code == 201
                await asyncio.wait_for(briefing_interrupted.wait(), timeout=3)

    with sqlite3.connect(database_path) as connection:
        due_at, finished, weather = connection.execute(
            "SELECT weather_refresh_due_at, weather_refresh_finished, weather_auto FROM store_daily_records WHERE store_id = 1 AND date = ?",
            (interrupted_date,),
        ).fetchone()
        assert due_at is not None and finished == 1 and weather == "晴"

    recovered_app = build_app(no_weather)
    async with recovered_app.router.lifespan_context(recovered_app):
        await recovered_app.state.background_refresh_scheduler.stop()
        async with AsyncClient(
            transport=ASGITransport(app=recovered_app), base_url="http://testserver"
        ) as client:
            assert (
                await client.post(
                    "/api/auth/login", json={"username": "weather-admin", "password": "secret"}
                )
            ).status_code == 200

            async def recovered_briefing():
                while True:
                    cards = (await client.get("/api/dashboard/1")).json()
                    if any(
                        card["card_type"] == "yesterday" and card["revenue"] == 441
                        for card in cards
                    ):
                        return
                    await asyncio.sleep(0)

            await asyncio.wait_for(recovered_briefing(), timeout=3)
    with sqlite3.connect(database_path) as connection:
        assert (
            connection.execute(
                "SELECT weather_refresh_due_at FROM store_daily_records WHERE store_id = 1 AND date = ?",
                (interrupted_date,),
            ).fetchone()[0]
            is None
        )
    assert no_weather.calls == 0
    await engine.dispose()
