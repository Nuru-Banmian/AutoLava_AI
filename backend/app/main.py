from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.api.router import api_router
from app.agents import ChatRunner
from app.agents.assistant.graph import ChatModel
from app.agents.providers.bailian import BailianChat
from app.agents.runtime.repository import ChatRepository
from app.api.routes.dashboard import RefreshLimiter
from app.core.config import get_settings
from app.core.database import async_session_factory, engine
from app.services.backup_copy import SshBackupDestination
from app.services.scheduler import (
    BackgroundRefreshScheduler,
    DailyScheduler,
    make_refresh_callback,
    make_sqlite_maintenance_callback,
)
from app.services.sqlite_backup import has_valid_backup
from app.services.pending_weather import PendingWeatherRefresh
from app.services.weather import OpenMeteoProvider, WeatherService


def create_app(
    *,
    session_factory: async_sessionmaker[AsyncSession] = async_session_factory,
    weather_service: WeatherService | None = None,
    agent_model: ChatModel | None = None,
    memory_model: ChatModel | None = None,
    embedding=None,
    vectors=None,
) -> FastAPI:
    settings = get_settings()
    agent_runner = ChatRunner(
        agent_model if agent_model is not None else BailianChat(settings),
        ChatRepository(session_factory), settings, memory_model=memory_model,
        embedding=embedding, vectors=vectors,
    )
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
        copy_destination = None
        copy_fields = (
            settings.backup_ssh_host, settings.backup_ssh_user,
            settings.backup_ssh_directory, settings.backup_ssh_key_file,
            settings.backup_ssh_known_hosts_file,
        )
        if any(copy_fields):
            if not all(copy_fields):
                raise ValueError("Backup SSH destination is incomplete")
            copy_destination = SshBackupDestination(
                settings.backup_ssh_host, settings.backup_ssh_user,
                settings.backup_ssh_directory, settings.backup_ssh_key_file,
                settings.backup_ssh_known_hosts_file,
            )
        maintenance_scheduler = DailyScheduler(
            make_sqlite_maintenance_callback(
                session_factory,
                source=settings.database_path,
                destination=settings.backup_directory,
                timezone=maintenance_timezone,
                copy_destination=copy_destination,
            ),
            timezone=maintenance_timezone,
            hour=3,
            startup_complete=lambda today: (
                copy_destination is None
                and has_valid_backup(settings.backup_directory, today)
            ),
        )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        await agent_runner.storage.recover()
        agent_runner.index.start()
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
            await agent_runner.close()
            if maintenance_scheduler is not None:
                await maintenance_scheduler.stop()
            await scheduler.stop()
            await pending_weather.stop()
            await provider.aclose()

    app = FastAPI(title="门店管理系统 API", lifespan=lifespan)
    app.state.agent_runner = agent_runner
    app.state.open_meteo_provider = provider
    app.state.weather_service = weather_service
    app.state.dashboard_refresh_limiter = RefreshLimiter()
    app.state.background_refresh_scheduler = scheduler
    app.state.pending_weather_refresh = pending_weather
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

    @app.get("/ready", response_model=None)
    async def ready() -> dict[str, str] | JSONResponse:
        try:
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1 FROM users LIMIT 1"))
        except (SQLAlchemyError, OSError):
            return JSONResponse({"status": "unavailable"}, status_code=503)
        return {"status": "ready"}

    return app


app = create_app()
