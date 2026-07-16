from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.operations import DailyBriefing
from app.schemas.dashboard import DashboardCardResponse
from app.services.weather import WeatherResult, WeatherService

_CARD_ORDER = {"yesterday": 0, "today": 1, "tomorrow": 2}
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class BriefingService:
    def __init__(self, session: AsyncSession, weather_service: WeatherService):
        self.session = session
        self.weather_service = weather_service

    async def _weather(self, store: Store, target: date) -> WeatherResult | None:
        try:
            return await self.weather_service.get_daily(store, target)
        except Exception:
            return None

    async def _record(self, store_id: int, target: date) -> StoreDailyRecord | None:
        return await self.session.scalar(
            select(StoreDailyRecord).where(
                StoreDailyRecord.store_id == store_id,
                StoreDailyRecord.date == target,
            )
        )

    async def build_yesterday(self, *, store_id: int, local_date: date) -> DashboardCardResponse:
        record = await self._record(store_id, local_date - timedelta(days=1))
        if record is None:
            state = "missing"
            revenue = None
        elif record.is_open == "休息":
            state = "rest"
            revenue = None
        elif record.is_open == "天气停业":
            state = "weather_closed"
            revenue = None
        else:
            state = "recorded"
            revenue = record.daily_revenue
        return DashboardCardResponse(
            card_type="yesterday",
            state=state,
            revenue=revenue,
            generated_at=datetime.now(UTC),
        )

    async def build_today(
        self,
        *,
        store: Store,
        local_date: date,
        weather_override: str | None = None,
    ) -> DashboardCardResponse:
        result = None if weather_override is not None else await self._weather(store, local_date)
        record = await self._record(store.id, local_date)
        if record is None:
            state = "missing"
            revenue = None
        elif record.is_open == "休息":
            state = "rest"
            revenue = None
        elif record.is_open == "天气停业":
            state = "weather_closed"
            revenue = None
        else:
            state = "recorded"
            revenue = record.daily_revenue
        return DashboardCardResponse(
            card_type="today",
            state=state,
            revenue=revenue,
            weather=weather_override or (result.weather if result is not None else None),
            generated_at=datetime.now(UTC),
        )

    async def build_tomorrow(self, *, store: Store, local_date: date) -> DashboardCardResponse:
        target = local_date + timedelta(days=1)
        result = await self._weather(store, target)
        return DashboardCardResponse(
            card_type="tomorrow",
            state="forecast" if result is not None else "unavailable",
            weather=result.weather if result is not None else None,
            weekday=_WEEKDAYS[target.weekday()],
            temperature_max=(Decimal(str(result.temperature_max)) if result is not None else None),
            temperature_min=(Decimal(str(result.temperature_min)) if result is not None else None),
            precipitation=(Decimal(str(result.precipitation)) if result is not None else None),
            generated_at=datetime.now(UTC),
        )

    @staticmethod
    def _content(card: DashboardCardResponse) -> str:
        if card.card_type == "yesterday":
            if card.state == "missing":
                return "昨天还没有经营记录，可以在记账页补录。"
            if card.state == "rest":
                return "昨天休息。"
            if card.state == "weather_closed":
                return "昨天因天气停业。"
            return f"昨天营业，营业额 €{card.revenue:.2f}。"
        weather = card.weather or "天气暂时不可用"
        if card.card_type == "today":
            if card.state == "missing":
                status = "还未记账"
            elif card.state == "recorded":
                status = f"已记账，营业额 €{card.revenue:.2f}"
            elif card.state == "rest":
                status = "休息"
            else:
                status = "天气停业"
            return f"今天：{weather}；{status}。"
        return f"明天（{card.weekday}）：{weather}。"

    async def regenerate(
        self,
        store_id: int,
        card_types: list[str],
        *,
        local_date: date | None = None,
        weather_overrides: dict[date, str] | None = None,
    ) -> list[DailyBriefing]:
        store = await self.session.get(Store, store_id)
        if store is None:
            return []
        if local_date is None:
            from zoneinfo import ZoneInfo

            local_date = datetime.now(ZoneInfo(store.timezone)).date()
        requested = sorted(set(card_types), key=lambda item: _CARD_ORDER.get(item, 99))
        cards = []
        for card_type in requested:
            if card_type == "yesterday":
                response = await self.build_yesterday(store_id=store.id, local_date=local_date)
            elif card_type == "today":
                response = await self.build_today(
                    store=store,
                    local_date=local_date,
                    weather_override=(weather_overrides or {}).get(local_date),
                )
            elif card_type == "tomorrow":
                response = await self.build_tomorrow(store=store, local_date=local_date)
            else:
                continue
            content = self._content(response)
            payload = response.model_dump(mode="json")
            statement = mysql_insert(DailyBriefing).values(
                store_id=store_id,
                card_type=card_type,
                content=content,
                payload=payload,
                generated_at=datetime.now(UTC).replace(tzinfo=None),
            )
            await self.session.execute(
                statement.on_duplicate_key_update(
                    content=statement.inserted.content,
                    payload=statement.inserted.payload,
                    generated_at=datetime.now(UTC).replace(tzinfo=None),
                )
            )
            card = await self.session.scalar(
                select(DailyBriefing)
                .where(
                    DailyBriefing.store_id == store_id,
                    DailyBriefing.card_type == card_type,
                )
                .with_for_update()
                .execution_options(populate_existing=True)
            )
            assert card is not None
            cards.append(card)
        return cards
