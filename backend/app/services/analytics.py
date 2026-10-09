from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementRecord
from app.services.business_metrics import rounded_average, rounded_percent
from app.services.weather import LEGACY_WEATHER_LABEL, RECORD_WEATHER_OPTIONS, is_legacy_weather
from app.services.ledger_statistics import OPERATING_STATES, period_coverage, statistical_records

WEATHER_GROUP_ORDER = {
    weather: index for index, weather in enumerate(RECORD_WEATHER_OPTIONS)
}


def _weather_group_order(weather: str) -> tuple[int, str]:
    if weather == LEGACY_WEATHER_LABEL:
        return len(WEATHER_GROUP_ORDER) + 1, weather
    if weather == "未记录":
        return len(WEATHER_GROUP_ORDER) + 2, weather
    return WEATHER_GROUP_ORDER.get(weather, len(WEATHER_GROUP_ORDER)), weather


def _rounded_average(total: int, count: int) -> int:
    """Round fractional euro averages to a whole euro using ROUND_HALF_UP."""
    return rounded_average(total, count)


@dataclass(frozen=True)
class CompositionKey:
    category_id: int
    category_name: str
    include_in_total: bool
    sort_order: int = field(compare=False)


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
    total = sum(record.daily_revenue for record in statistical_records(records))
    operating_records = [
        record for record in records if record.is_open in OPERATING_STATES
    ]
    operating_day_count = len(operating_records)
    operating_revenue = sum(record.daily_revenue for record in operating_records)
    return {
        "total_revenue": total,
        "record_days": len(records),
        "open_days": operating_day_count,
        "average_revenue": _rounded_average(
            operating_revenue, operating_day_count
        ),
    }


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _daily_revenue_rows(records: list[StoreDailyRecord]) -> list[dict[str, object]]:
    return [
        {
            "date": record.date.isoformat(),
            "revenue": record.daily_revenue,
            "is_open": record.is_open,
        }
        for record in records
    ]


def _monthly_revenue_rows(
    daily_by_month: dict[str, int],
    settlement_by_month: dict[str, int],
    recorded_months: set[str],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for month in sorted(daily_by_month.keys() | settlement_by_month.keys() | recorded_months):
        daily_revenue = daily_by_month.get(month)
        settlement_income = settlement_by_month.get(month, 0)
        rows.append(
            {
                "month": month,
                "revenue": daily_revenue,
                "daily_ledger_revenue": daily_revenue,
                "confirmed_settlement_income": settlement_income,
                "monthly_total_income": (daily_revenue or 0) + settlement_income if daily_revenue is not None or month in settlement_by_month else None,
            }
        )
    return rows


class AnalyticsService:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _confirmed_settlement_by_month(
        self, *, store_id: int, start: date, end: date
    ) -> dict[str, int]:
        first_month = _month_start(start)
        last_month = _month_start(end)
        rows = (
            await self.session.execute(
                select(
                    SettlementRecord.opening_month,
                    func.sum(SettlementRecord.amount),
                )
                .where(
                    SettlementRecord.store_id == store_id,
                    SettlementRecord.status == "confirmed",
                    SettlementRecord.opening_month >= first_month,
                    SettlementRecord.opening_month <= last_month,
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
        company_settlement_enabled: bool = False,
        compare_start: date | None = None,
        compare_end: date | None = None,
        bucket: Literal["day", "month"] = "day",
        local_date: date | None = None,
    ) -> dict:
        if (
            local_date is not None
            and (start.year, start.month) == (end.year, end.month)
            and (start.year, start.month) == (local_date.year, local_date.month)
        ):
            end = min(end, local_date)
        daily_compare_start, daily_compare_end = compare_start, compare_end
        short_previous_month = False
        if (
            local_date is not None
            and compare_start is None
            and start <= end
            and (start.year, start.month) == (end.year, end.month)
        ):
            previous_last = start.replace(day=1) - timedelta(days=1)
            short_previous_month = end.day > previous_last.day
            if start.day <= previous_last.day:
                daily_compare_start = previous_last.replace(day=start.day)
                daily_compare_end = previous_last.replace(day=min(end.day, previous_last.day))
        wash_count_enabled = await self.session.scalar(
            select(Store.wash_count_enabled).where(Store.id == store_id)
        )
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
        if daily_compare_start is not None and daily_compare_end is not None:
            comparison_records = (
                await self.session.scalars(
                    select(StoreDailyRecord)
                    .where(
                        StoreDailyRecord.store_id == store_id,
                        StoreDailyRecord.date.between(daily_compare_start, daily_compare_end),
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
        for record in statistical_records(records):
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
            if record.is_open in OPERATING_STATES:
                weather_group = (
                    LEGACY_WEATHER_LABEL if is_legacy_weather(record.weather)
                    else record.weather or "未记录"
                )
                weather_totals[weather_group].append(record.daily_revenue)
                weekday_totals[record.date.weekday()].append(record.daily_revenue)

        operating_records = [
            record for record in records if record.is_open in OPERATING_STATES
        ]
        covered_records = [
            record for record in operating_records if record.wash_count is not None
        ] if wash_count_enabled else []
        total_wash = sum(record.wash_count for record in covered_records) if covered_records else None
        covered_revenue = sum(record.daily_revenue for record in covered_records)
        coverage_status = None
        if wash_count_enabled:
            if not operating_records:
                coverage_status = "no_operating_days"
            elif not covered_records:
                coverage_status = "missing"
            elif len(covered_records) == len(operating_records):
                coverage_status = "complete"
            else:
                coverage_status = "partial"
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
        includes_settlement_income = (
            company_settlement_enabled or confirmed_settlement_income > 0
        )
        total_income = daily_ledger_revenue + confirmed_settlement_income
        # Complete composition is independent of the legacy category filter.
        # Keep historical item snapshots and the existing classified subtotal intact.
        income_composition = list(included_rows)
        unclassified_revenue = daily_ledger_revenue - classified_included_total
        if unclassified_revenue:
            income_composition.append({
                "category_id": None,
                "category_name": "未分类营业额",
                "amount": unclassified_revenue,
            })
        if confirmed_settlement_income:
            income_composition.append({
                "category_id": None,
                "category_name": "公司结算",
                "amount": confirmed_settlement_income,
            })
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
                "wash_count_covered_days": len(covered_records) if wash_count_enabled else None,
                "wash_count_coverage_status": coverage_status,
                "average_ticket": (
                    _rounded_average(covered_revenue, total_wash)
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

        previous_revenue = None
        change_percent = None
        comparison_coverage = None
        comparison_status = "no_comparison"
        if daily_compare_start is not None and daily_compare_end is not None:
            previous_revenue = sum(record.daily_revenue for record in statistical_records(comparison_records))
            comparison_coverage = period_coverage(comparison_records, daily_compare_start, daily_compare_end)
            if not statistical_records(comparison_records):
                comparison_status = "no_previous_records"
            elif previous_revenue == 0:
                comparison_status = "zero_previous"
            elif not statistical_records(records):
                comparison_status = "no_current_records"
            else:
                comparison_status = "comparable"
                change_percent = rounded_percent(
                    daily_ledger_revenue - previous_revenue, previous_revenue
                )

        return {
            "kpis": kpis,
            "range": {
                "start": start.isoformat(),
                "end": end.isoformat(),
                "bucket": bucket,
            },
            "comparison_kpis": comparison_kpis,
            "comparison_coverage": comparison_coverage,
            "ledger_comparison": {
                "current_revenue": daily_ledger_revenue,
                "previous_revenue": previous_revenue,
                "change_percent": change_percent,
                "status": comparison_status,
                "short_previous_month": short_previous_month,
            },
            "comparison_daily": _daily_revenue_rows(comparison_records),
            "income_summary": {
                "daily_ledger_revenue": daily_ledger_revenue,
                "confirmed_settlement_income": confirmed_settlement_income,
                "total_income": total_income,
                "includes_settlement_income": includes_settlement_income,
            },
            "classified_included_total": classified_included_total,
            "period_coverage": period_coverage(records, start, end),
            "daily": _daily_revenue_rows(records),
            "categories": compositions,
            "income_composition": income_composition,
            "excluded_categories": excluded_rows,
            "monthly": _monthly_revenue_rows(
                monthly_totals,
                settlement_by_month,
                {record.date.strftime("%Y-%m") for record in records},
            ),
            "weather": [
                {
                    "weather": weather,
                    "average_revenue": _rounded_average(sum(values), len(values)),
                    "operating_day_count": len(values),
                }
                for weather, values in sorted(
                    weather_totals.items(), key=lambda row: _weather_group_order(row[0])
                )
            ],
            "weekday": [
                {
                    "weekday": weekday,
                    "average_revenue": _rounded_average(sum(values), len(values)),
                    "operating_day_count": len(values),
                }
                for weekday, values in sorted(weekday_totals.items())
            ],
        }
