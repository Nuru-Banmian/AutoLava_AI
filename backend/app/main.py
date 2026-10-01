from contextlib import asynccontextmanager
from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.router import api_router
from app.api.routes.dashboard import RefreshLimiter
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.services.scheduler import (
    BackgroundRefreshScheduler,
    DailyScheduler,
    make_refresh_callback,
    make_sqlite_maintenance_callback,
)
from app.services.sqlite_backup import has_valid_backup
from app.services.pending_weather import PendingWeatherRefresh
from app.services.agent_chat import AgentChatGraph, OpenAICompatibleChatModel
from app.services.weather import OpenMeteoProvider, WeatherService


def create_app(
    *,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    weather_service: WeatherService | None = None,
) -> FastAPI:
    settings = get_settings()
    provider = OpenMeteoProvider(max_inflight=settings.weather_max_inflight)
    if weather_service is None:
        weather_service = WeatherService(provider)
    scheduler = BackgroundRefreshScheduler(
        make_refresh_callback(session_factory, weather_service)
    )
    pending_weather = PendingWeatherRefresh(
        session_factory, lambda: app.state.weather_service
    )
    maintenance_scheduler: DailyScheduler | None = None
    if settings.environment.lower() == "production":
        maintenance_timezone = ZoneInfo(settings.maintenance_timezone)
        maintenance_scheduler = DailyScheduler(
            make_sqlite_maintenance_callback(
                session_factory,
                source=settings.database_path,
                destination=settings.backup_directory,
                timezone=maintenance_timezone,
            ),
            timezone=maintenance_timezone,
            hour=3,
            startup_complete=lambda today: has_valid_backup(
                settings.backup_directory, today
            ),
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        provider.client = httpx.AsyncClient(
            limits=httpx.Limits(max_connections=settings.weather_max_inflight),
            timeout=httpx.Timeout(8),
        )
        pending_weather.start()
        scheduler.start()
        if maintenance_scheduler is not None:
            maintenance_scheduler.start()
        try:
            yield
        finally:
            if maintenance_scheduler is not None:
                await maintenance_scheduler.stop()
            await scheduler.stop()
            await pending_weather.stop()
            await provider.aclose()

    app = FastAPI(title="AutoLava AI API", lifespan=lifespan)
    app.state.open_meteo_provider = provider
    app.state.weather_service = weather_service
    app.state.dashboard_refresh_limiter = RefreshLimiter()
    app.state.background_refresh_scheduler = scheduler
    app.state.pending_weather_refresh = pending_weather
    app.state.agent_chat_graph = AgentChatGraph(OpenAICompatibleChatModel(settings))
    app.state.agent_clock = lambda: datetime.now(UTC)
    if maintenance_scheduler is not None:
        # Retention is chained after every backup attempt, so both names expose
        # the same single 03:00 lifecycle owner.
        app.state.sqlite_backup_scheduler = maintenance_scheduler
        app.state.operations_retention_scheduler = maintenance_scheduler
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router)

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
