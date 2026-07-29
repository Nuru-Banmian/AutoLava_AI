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
from app.services.agent_model import BailianOpenAIModelAdapter
from app.services.agent_turn import AgentTurnRuntime
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
        await app.state.agent_turn_runtime.recover_interrupted_turns()
        scheduler.start()
        if maintenance_scheduler is not None:
            maintenance_scheduler.start()
        try:
            yield
        finally:
            await app.state.agent_turn_runtime.stop()
            if maintenance_scheduler is not None:
                await maintenance_scheduler.stop()
            await scheduler.stop()

    app = FastAPI(title="AutoLava AI API", lifespan=lifespan)
    app.state.open_meteo_provider = provider
    app.state.weather_service = weather_service
    app.state.dashboard_refresh_limiter = RefreshLimiter()
    app.state.background_refresh_scheduler = scheduler
    app.state.agent_model_adapter = BailianOpenAIModelAdapter(settings)
    app.state.agent_session_factory = async_session_factory
    app.state.agent_turn_runtime = AgentTurnRuntime(
        lambda: app.state.agent_session_factory(),
        lambda: app.state.agent_model_adapter,
        turn_timeout_seconds=settings.agent_turn_timeout_seconds,
        stop_new_tools_seconds=settings.agent_stop_new_tools_seconds,
        model_round_limit=settings.agent_model_round_limit,
        data_tool_call_limit=settings.agent_data_tool_call_limit,
        data_tool_timeout_seconds=settings.agent_data_tool_timeout_seconds,
        transient_retry_limit=settings.agent_transient_retry_limit,
    )
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
