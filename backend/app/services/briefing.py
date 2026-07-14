from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.operations import DailyBriefing
from app.services.weather import WeatherService

_CARD_ORDER = {"yesterday": 0, "today": 1, "tomorrow": 2}
_WEEKDAYS = ("星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日")


class BriefingService:
    def __init__(self, session: AsyncSession, weather_service: WeatherService):
        self.session = session
        self.weather_service = weather_service

    async def _weather(self, store: Store, target: date) -> str:
        try:
            result = await self.weather_service.get_daily(store, target)
        except Exception:
            result = None
        return result.weather if result is not None else "天气暂时不可用"

    async def _record(self, store_id: int, target: date) -> StoreDailyRecord | None:
        return await self.session.scalar(
            select(StoreDailyRecord).where(
                StoreDailyRecord.store_id == store_id,
                StoreDailyRecord.date == target,
            )
        )

    async def _leading_categories(self, record_id: int) -> list[tuple[str, Decimal]]:
        rows = await self.session.execute(
            select(IncomeCategory.name, DailyIncomeItem.amount)
            .join(DailyIncomeItem, DailyIncomeItem.category_id == IncomeCategory.id)
            .where(
                DailyIncomeItem.record_id == record_id,
                IncomeCategory.include_in_total.is_(True),
                DailyIncomeItem.amount > 0,
            )
            .order_by(
                DailyIncomeItem.amount.desc(),
                IncomeCategory.sort_order,
                IncomeCategory.id,
            )
            .limit(3)
        )
        return [(name, amount) for name, amount in rows]

    async def _yesterday(self, store: Store, local_date: date) -> str:
        record = await self._record(store.id, local_date - timedelta(days=1))
        if record is None:
            return "昨天还没有经营记录，可以在记账页补录。"
        parts = [f"昨天{record.is_open}，营业额 €{record.daily_revenue:.2f}"]
        categories = await self._leading_categories(record.id)
        if categories:
            parts.append(
                "主要收入：" + "、".join(f"{name} €{amount:.2f}" for name, amount in categories)
            )
        if record.weather:
            parts.append(f"天气：{record.weather}")
        if record.wash_count is not None:
            parts.append(f"洗车 {record.wash_count} 辆")
        if record.activity and record.activity.strip():
            parts.append(f"活动：{record.activity.strip()}")
        return "；".join(parts) + "。"

    async def _today(self, store: Store, local_date: date) -> str:
        weather = await self._weather(store, local_date)
        record = await self._record(store.id, local_date)
        if record is None:
            status = "还未记账"
        else:
            status = f"已记账，营业额 €{record.daily_revenue:.2f}"
        return f"今天：{weather}；{status}。"

    async def _tomorrow(self, store: Store, local_date: date) -> str:
        target = local_date + timedelta(days=1)
        weather = await self._weather(store, target)
        return f"明天（{_WEEKDAYS[target.weekday()]}）：{weather}。"

    async def regenerate(
        self,
        store_id: int,
        card_types: list[str],
        *,
        local_date: date | None = None,
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
                content = await self._yesterday(store, local_date)
            elif card_type == "today":
                content = await self._today(store, local_date)
            elif card_type == "tomorrow":
                content = await self._tomorrow(store, local_date)
            else:
                continue
            statement = mysql_insert(DailyBriefing).values(
                store_id=store_id,
                card_type=card_type,
                content=content,
            )
            await self.session.execute(
                statement.on_duplicate_key_update(
                    content=statement.inserted.content,
                    generated_at=datetime.now(),
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
