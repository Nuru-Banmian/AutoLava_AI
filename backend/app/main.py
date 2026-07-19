from contextlib import asynccontextmanager
from zoneinfo import ZoneInfo

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

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
from app.services.weather import OpenMeteoProvider, WeatherService


def create_app() -> FastAPI:
    settings = get_settings()
    provider = OpenMeteoProvider()
    weather_service = WeatherService(provider)
    scheduler = BackgroundRefreshScheduler(
        make_refresh_callback(async_session_factory, weather_service)
    )
    maintenance_scheduler: DailyScheduler | None = None
    if settings.environment.lower() == "production":
        maintenance_timezone = ZoneInfo(settings.maintenance_timezone)
        maintenance_scheduler = DailyScheduler(
            make_sqlite_maintenance_callback(
                async_session_factory,
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
        scheduler.start()
        if maintenance_scheduler is not None:
            maintenance_scheduler.start()
        try:
            yield
        finally:
            if maintenance_scheduler is not None:
                await maintenance_scheduler.stop()
            await scheduler.stop()

    app = FastAPI(title="AutoLava AI API", lifespan=lifespan)
    app.state.open_meteo_provider = provider
    app.state.weather_service = weather_service
    app.state.dashboard_refresh_limiter = RefreshLimiter()
    app.state.background_refresh_scheduler = scheduler
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
