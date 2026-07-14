import asyncio
from unittest.mock import AsyncMock

from app.models.ledger import StoreDailyRecord
from app.main import create_app
from app.services.scheduler import BackgroundRefreshScheduler, apply_refreshed_weather
from app.services.weather import WeatherResult


def test_refreshed_weather_preserves_user_edited_final_value() -> None:
    record = StoreDailyRecord(weather="手工天气", weather_auto="旧天气", weather_edited=True)

    apply_refreshed_weather(record, WeatherResult("晴", 0, 30.0, 20.0, 0.0))

    assert record.weather == "手工天气"
    assert record.weather_auto == "晴"
    assert record.weather_code == 0


async def test_background_refresh_is_bounded_and_can_be_stopped() -> None:
    async def hang() -> None:
        await asyncio.sleep(60)

    never_finishes = AsyncMock(side_effect=hang)
    scheduler = BackgroundRefreshScheduler(
        never_finishes, interval_seconds=0.01, timeout_seconds=0.01
    )

    scheduler.start()
    await asyncio.sleep(0.04)
    await scheduler.stop()

    assert never_finishes.await_count >= 1
    assert scheduler.running is False


async def test_background_refresh_survives_weather_failure() -> None:
    failure = AsyncMock(side_effect=RuntimeError("weather offline"))
    scheduler = BackgroundRefreshScheduler(failure, interval_seconds=0.01, timeout_seconds=0.1)

    scheduler.start()
    await asyncio.sleep(0.04)
    await scheduler.stop()

    assert failure.await_count >= 2
    assert scheduler.running is False


async def test_app_lifespan_starts_and_stops_background_refresh() -> None:
    app = create_app()
    scheduler = app.state.background_refresh_scheduler
    scheduler.refresh = AsyncMock()

    async with app.router.lifespan_context(app):
        await asyncio.sleep(0)
        assert scheduler.running is True

    assert scheduler.running is False
