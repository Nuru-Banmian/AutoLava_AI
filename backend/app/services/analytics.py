from collections import defaultdict
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementRecord


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


def _is_complete_month_range(start: date, end: date) -> bool:
    return start.day == 1 and end.day == monthrange(end.year, end.month)[1]


def _monthly_revenue_rows(
    daily_by_month: dict[str, int],
    settlement_by_month: dict[str, int],
    *,
    include_settlement: bool,
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for month in sorted(daily_by_month.keys() | settlement_by_month.keys()):
        daily_revenue = daily_by_month.get(month, 0)
        settlement_income = (
            settlement_by_month.get(month, 0) if include_settlement else None
        )
        rows.append(
            {
                "month": month,
                "revenue": daily_revenue,
                "daily_ledger_revenue": daily_revenue,
                "confirmed_settlement_income": settlement_income,
                "monthly_total_income": (
                    daily_revenue + settlement_income
                    if settlement_income is not None
                    else None
                ),
            }
        )
    return rows


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _confirmed_settlement_by_month(
        self, *, store_id: int, start: date, end: date
    ) -> dict[str, int]:
        if not _is_complete_month_range(start, end):
            return {}
        rows = (
            await self.session.execute(
                select(
                    SettlementRecord.opening_month,
                    func.sum(SettlementRecord.amount),
                )
                .where(
                    SettlementRecord.store_id == store_id,
                    SettlementRecord.status == "confirmed",
                    SettlementRecord.opening_month >= start,
                    SettlementRecord.opening_month <= end,
                )
                .group_by(SettlementRecord.opening_month)
            )
        ).tuples()
        return {
            opening_month.strftime("%Y-%m"): int(amount)
            for opening_month, amount in rows
        }

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

        settlement_by_month = await self._confirmed_settlement_by_month(
            store_id=store_id, start=start, end=end
        )
        comparison_settlement_by_month: dict[str, int] = {}
        if compare_start is not None and compare_end is not None:
            comparison_settlement_by_month = await self._confirmed_settlement_by_month(
                store_id=store_id, start=compare_start, end=compare_end
            )
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
        daily_ledger_revenue = kpis["total_revenue"]
        confirmed_settlement_income = sum(settlement_by_month.values())
        total_income = daily_ledger_revenue + confirmed_settlement_income
        if confirmed_settlement_income:
            compositions.append(
                {
                    "category_id": None,
                    "category_name": "公司结算",
                    "amount": confirmed_settlement_income,
                }
            )
            classified_included_total += confirmed_settlement_income
        kpis["total_revenue"] = total_income
        kpis.update(
            {
                "primary_categories": primary_categories,
                "total_wash_count": total_wash,
                "average_ticket": (
                    _rounded_average(daily_ledger_revenue, total_wash)
                    if total_wash is not None and total_wash > 0
                    else None
                ),
            }
        )
        comparison_kpis = None
        if compare_start is not None and compare_end is not None:
            comparison = _revenue_kpis(comparison_records)
            comparison["total_revenue"] += sum(
                comparison_settlement_by_month.values()
            )
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
            "income_summary": {
                "daily_ledger_revenue": daily_ledger_revenue,
                "confirmed_settlement_income": confirmed_settlement_income,
                "total_income": total_income,
                "includes_settlement_income": _is_complete_month_range(start, end),
            },
            "classified_included_total": classified_included_total,
            "daily": [
                {"date": record.date.isoformat(), "revenue": record.daily_revenue}
                for record in records
            ],
            "categories": compositions,
            "excluded_categories": excluded_rows,
            "monthly": _monthly_revenue_rows(
                monthly_totals,
                settlement_by_month,
                include_settlement=_is_complete_month_range(start, end),
            ),
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
