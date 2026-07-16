from collections.abc import Callable
from datetime import date
from time import monotonic
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import case, select

from app.api.deps import Session, StoreAccess, require_store_access
from app.models.operations import DailyBriefing
from app.schemas.dashboard import DashboardCardResponse
from app.services.briefing import BriefingService
from app.services.weather import WeatherResult, WeatherService

router = APIRouter(tags=["dashboard"])


class RefreshLimiter:
    def __init__(
        self,
        *,
        interval_seconds: float = 300,
        clock: Callable[[], float] = monotonic,
    ):
        self.interval_seconds = interval_seconds
        self.clock = clock
        self._last_refresh: dict[tuple[int, int], float] = {}

    def allow(self, *, user_id: int, store_id: int) -> bool:
        now = self.clock()
        key = (user_id, store_id)
        previous = self._last_refresh.get(key)
        if previous is not None and now - previous < self.interval_seconds:
            return False
        self._last_refresh[key] = now
        return True


def get_weather_service(request: Request) -> WeatherService:
    return request.app.state.weather_service


Weather = Annotated[WeatherService, Depends(get_weather_service)]


def _card_payload(card: DailyBriefing) -> DashboardCardResponse:
    if card.payload is not None:
        return DashboardCardResponse.model_validate(card.payload)
    return DashboardCardResponse(
        card_type=card.card_type,
        state="unavailable",
        generated_at=card.generated_at,
    )


def _weather_payload(result: WeatherResult | None) -> dict[str, str | int | float | None]:
    if result is None:
        return {
            "weather": None,
            "weather_code": None,
            "temperature_max": None,
            "temperature_min": None,
            "precipitation": None,
        }
    return {
        "weather": result.weather,
        "weather_code": result.weather_code,
        "temperature_max": result.temperature_max,
        "temperature_min": result.temperature_min,
        "precipitation": result.precipitation,
    }


@router.get("/weather/{store_id}/{target_date}")
async def get_weather(
    store_id: int,
    target_date: date,
    weather: Weather,
    access: StoreAccess = Depends(require_store_access),
) -> dict[str, str | int | float | None]:
    try:
        result = await weather.get_daily(access.store, target_date)
    except Exception:
        result = None
    return _weather_payload(result)


@router.get("/dashboard/{store_id}")
async def get_dashboard(
    store_id: int,
    session: Session,
    access: StoreAccess = Depends(require_store_access),
) -> list[DashboardCardResponse]:
    card_order = case(
        (DailyBriefing.card_type == "yesterday", 0),
        (DailyBriefing.card_type == "today", 1),
        (DailyBriefing.card_type == "tomorrow", 2),
        else_=99,
    )
    cards = await session.scalars(
        select(DailyBriefing)
        .where(DailyBriefing.store_id == access.store.id)
        .order_by(card_order, DailyBriefing.id)
    )
    return [_card_payload(card) for card in cards]


@router.post("/dashboard/{store_id}/refresh")
async def refresh_dashboard(
    store_id: int,
    request: Request,
    session: Session,
    weather: Weather,
    access: StoreAccess = Depends(require_store_access),
) -> list[DashboardCardResponse]:
    limiter: RefreshLimiter = request.app.state.dashboard_refresh_limiter
    if not limiter.allow(user_id=access.user.id, store_id=access.store.id):
        raise HTTPException(429, "请等待五分钟后再刷新")
    cards = await BriefingService(session, weather).regenerate(
        access.store.id, ["yesterday", "today", "tomorrow"]
    )
    await session.commit()
    return [_card_payload(card) for card in cards]
