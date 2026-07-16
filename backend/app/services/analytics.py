from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ledger import IncomeCategory, StoreDailyRecord

MONEY = Decimal("0.01")


def _money(value: Decimal) -> str:
    return str(value.quantize(MONEY, rounding=ROUND_HALF_UP))


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def calculate(
        self,
        *,
        store_id: int,
        start: date,
        end: date,
        category_ids: list[int],
    ) -> dict:
        records = (
            await self.session.scalars(
                select(StoreDailyRecord)
                .options(selectinload(StoreDailyRecord.items))
                .where(
                    StoreDailyRecord.store_id == store_id,
                    StoreDailyRecord.date.between(start, end),
                )
                .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
            )
        ).all()
        categories = (
            await self.session.scalars(
                select(IncomeCategory)
                .where(
                    IncomeCategory.store_id == store_id,
                    IncomeCategory.id.in_(category_ids),
                )
                .order_by(IncomeCategory.sort_order, IncomeCategory.id)
            )
        ).all()
        category_names = {category.id: category.name for category in categories}
        selected = set(category_names)

        total = sum((record.daily_revenue for record in records), Decimal("0.00"))
        open_days = sum(record.is_open == "营业" for record in records)
        category_totals: dict[int, Decimal] = defaultdict(lambda: Decimal("0.00"))
        monthly_totals: dict[str, Decimal] = defaultdict(lambda: Decimal("0.00"))
        weather_totals: dict[str, list[Decimal]] = defaultdict(list)
        weekday_totals: dict[int, list[Decimal]] = defaultdict(list)
        for record in records:
            for item in record.items:
                if item.category_id in selected:
                    category_totals[item.category_id] += item.amount
            monthly_totals[record.date.strftime("%Y-%m")] += record.daily_revenue
            weather_totals[record.weather or "未记录"].append(record.daily_revenue)
            weekday_totals[record.date.weekday()].append(record.daily_revenue)

        recorded_wash = [record.wash_count for record in records if record.wash_count is not None]
        total_wash = sum(recorded_wash) if recorded_wash else None
        compositions = [
            {
                "category_id": category.id,
                "category_name": category.name,
                "amount": _money(category_totals[category.id]),
            }
            for category in categories
            if category.id in category_totals
        ]
        primary_categories = sorted(
            compositions,
            key=lambda item: (-Decimal(item["amount"]), item["category_id"]),
        )[:3]

        return {
            "kpis": {
                "total_revenue": _money(total),
                "record_days": len(records),
                "open_days": open_days,
                "average_revenue": _money(total / open_days) if open_days else _money(Decimal()),
                "primary_categories": primary_categories,
                "total_wash_count": total_wash,
                "average_ticket": (
                    _money(total / total_wash)
                    if total_wash is not None and total_wash > 0
                    else None
                ),
            },
            "daily": [
                {"date": record.date.isoformat(), "revenue": _money(record.daily_revenue)}
                for record in records
            ],
            "categories": compositions,
            "monthly": [
                {"month": month, "revenue": _money(revenue)}
                for month, revenue in sorted(monthly_totals.items())
            ],
            "weather": [
                {
                    "weather": weather,
                    "average_revenue": _money(sum(values) / len(values)),
                }
                for weather, values in sorted(weather_totals.items())
            ],
            "weekday": [
                {
                    "weekday": weekday,
                    "average_revenue": _money(sum(values) / len(values)),
                }
                for weekday, values in sorted(weekday_totals.items())
            ],
        }
