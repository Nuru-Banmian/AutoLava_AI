from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.routes.dashboard import RefreshLimiter
from app.core.config import get_settings
from app.core.database import async_session_factory
from app.services.scheduler import (
    BackgroundRefreshScheduler,
    make_refresh_callback,
    make_retention_callback,
)
from app.services.weather import OpenMeteoProvider, WeatherService


def create_app() -> FastAPI:
    settings = get_settings()
    provider = OpenMeteoProvider()
    weather_service = WeatherService(provider)
    scheduler = BackgroundRefreshScheduler(
        make_refresh_callback(async_session_factory, weather_service)
    )
    retention_scheduler = BackgroundRefreshScheduler(
        make_retention_callback(async_session_factory),
        interval_seconds=86400,
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        scheduler.start()
        retention_scheduler.start()
        try:
            yield
        finally:
            await scheduler.stop()
            await retention_scheduler.stop()

    app = FastAPI(title="AutoLava AI API", lifespan=lifespan)
    app.state.open_meteo_provider = provider
    app.state.weather_service = weather_service
    app.state.dashboard_refresh_limiter = RefreshLimiter()
    app.state.background_refresh_scheduler = scheduler
    app.state.background_retention_scheduler = retention_scheduler
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
