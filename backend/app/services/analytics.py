from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ledger import StoreDailyRecord


def _rounded_average(total: int, count: int) -> int:
    """Round fractional euro averages to a whole euro using ROUND_HALF_UP."""
    if count == 0:
        return 0
    return int(
        (Decimal(total) / Decimal(count)).quantize(Decimal("1"), rounding=ROUND_HALF_UP)
    )


@dataclass(frozen=True)
class CompositionKey:
    category_id: int
    category_name: str
    include_in_total: bool
    sort_order: int


def _composition_rows(totals: dict[CompositionKey, int]) -> list[dict]:
    return [
        {
            "category_id": key.category_id,
            "category_name": key.category_name,
            "amount": amount,
        }
        for key, amount in sorted(
            totals.items(),
            key=lambda row: (
                row[0].sort_order,
                row[0].category_id,
                row[0].category_name,
            ),
        )
    ]


def _revenue_kpis(records: list[StoreDailyRecord]) -> dict:
    total = sum(record.daily_revenue for record in records)
    open_days = sum(record.is_open == "营业" for record in records)
    return {
        "total_revenue": total,
        "record_days": len(records),
        "open_days": open_days,
        "average_revenue": _rounded_average(total, open_days),
    }


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def calculate(
        self,
        *,
        store_id: int,
        start: date,
        end: date,
        category_ids: list[int] | None,
        compare_start: date | None = None,
        compare_end: date | None = None,
        bucket: Literal["day", "month"] = "day",
    ) -> dict:
        records = (
            await self.session.scalars(
                select(StoreDailyRecord)
                .options(selectinload(StoreDailyRecord.items))
                .execution_options(populate_existing=True)
                .where(
                    StoreDailyRecord.store_id == store_id,
                    StoreDailyRecord.date.between(start, end),
                )
                .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
            )
        ).all()
        comparison_records: list[StoreDailyRecord] = []
        if compare_start is not None and compare_end is not None:
            comparison_records = (
                await self.session.scalars(
                    select(StoreDailyRecord)
                    .where(
                        StoreDailyRecord.store_id == store_id,
                        StoreDailyRecord.date.between(compare_start, compare_end),
                    )
                    .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
                )
            ).all()

        selected_ids = None if category_ids is None else set(category_ids)
        included_totals: dict[CompositionKey, int] = defaultdict(int)
        excluded_totals: dict[CompositionKey, int] = defaultdict(int)
        selected_totals: dict[CompositionKey, int] = defaultdict(int)
        monthly_totals: dict[str, int] = defaultdict(int)
        weather_totals: dict[str, list[int]] = defaultdict(list)
        weekday_totals: dict[int, list[int]] = defaultdict(list)
        for record in records:
            for item in record.items:
                key = CompositionKey(
                    category_id=item.category_id,
                    category_name=item.category_name,
                    include_in_total=item.include_in_total,
                    sort_order=item.sort_order,
                )
                if item.include_in_total:
                    included_totals[key] += item.amount
                else:
                    excluded_totals[key] += item.amount
                if selected_ids is not None and item.category_id in selected_ids:
                    selected_totals[key] += item.amount
            monthly_totals[record.date.strftime("%Y-%m")] += record.daily_revenue
            weather_totals[record.weather or "未记录"].append(record.daily_revenue)
            weekday_totals[record.date.weekday()].append(record.daily_revenue)

        recorded_wash = [
            record.wash_count for record in records if record.wash_count is not None
        ]
        total_wash = sum(recorded_wash) if recorded_wash else None
        included_rows = _composition_rows(included_totals)
        excluded_rows = _composition_rows(excluded_totals)
        compositions = (
            included_rows if category_ids is None else _composition_rows(selected_totals)
        )
        classified_included_total = sum(included_totals.values())
        primary_categories = sorted(
            compositions,
            key=lambda item: (-item["amount"], item["category_id"]),
        )[:3]
        kpis = _revenue_kpis(records)
        kpis.update(
            {
                "primary_categories": primary_categories,
                "total_wash_count": total_wash,
                "average_ticket": (
                    _rounded_average(kpis["total_revenue"], total_wash)
                    if total_wash is not None and total_wash > 0
                    else None
                ),
            }
        )
        comparison_kpis = None
        if compare_start is not None and compare_end is not None:
            comparison = _revenue_kpis(comparison_records)
            comparison_kpis = {
                "start": compare_start.isoformat(),
                "end": compare_end.isoformat(),
                "total_revenue": comparison["total_revenue"],
                "open_days": comparison["open_days"],
                "average_revenue": comparison["average_revenue"],
            }

        return {
            "kpis": kpis,
            "range": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "bucket": bucket,
            },
            "comparison_kpis": comparison_kpis,
            "classified_included_total": classified_included_total,
            "daily": [
                {"date": record.date.isoformat(), "revenue": record.daily_revenue}
                for record in records
            ],
            "categories": compositions,
            "excluded_categories": excluded_rows,
            "monthly": [
                {"month": month, "revenue": revenue}
                for month, revenue in sorted(monthly_totals.items())
            ],
            "weather": [
                {
                    "weather": weather,
                    "average_revenue": _rounded_average(sum(values), len(values)),
                }
                for weather, values in sorted(weather_totals.items())
            ],
            "weekday": [
                {
                    "weekday": weekday,
                    "average_revenue": _rounded_average(sum(values), len(values)),
                }
                for weekday, values in sorted(weekday_totals.items())
            ],
        }
