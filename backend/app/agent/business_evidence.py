from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, func, literal, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import (
    CalendarMonthPeriod,
    EvidenceBundle,
    EvidenceMetric,
    EvidencePeriodResult,
    EvidencePlan,
)
from app.agent.runtime import RuntimeContext
from app.models.ledger import DailyIncomeItem, StoreDailyRecord
from app.models.settlement import SettlementRecord

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
Now = Callable[[ZoneInfo], datetime]


@dataclass(frozen=True)
class Snapshot:
    daily_revenue: int
    operating_revenue: int
    operating_days: int
    confirmed_settlement: int
    recorded_dates: int
    categories: list[dict[str, object]]


class BusinessEvidenceCollector:
    """Collect one validated batch of business evidence in one SQLite snapshot."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        now: Now | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._now = now or (lambda timezone: datetime.now(timezone))

    async def collect(
        self,
        plan: EvidencePlan,
        context: RuntimeContext,
    ) -> EvidenceBundle:
        request = plan.requests[0]
        start, end = self._resolve_period(request.period, context)
        if request.metric == EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME:
            self._require_natural_month_period(start, end, context)

        for attempt in range(2):
            try:
                snapshot = await self._read_snapshot(
                    context=context,
                    start=start,
                    end=end,
                    metric=request.metric,
                )
                break
            except OperationalError as error:
                if attempt == 1 or not _is_temporary_sqlite_failure(error):
                    raise

        calendar_dates = (end - start).days + 1
        missing_dates = calendar_dates - snapshot.recorded_dates
        warnings = (
            [f"所选期间有 {missing_dates} 个日期没有每日台账；这不表示门店本应营业。"]
            if missing_dates
            else []
        )
        result, unit, version, summary = self._metric_result(
            metric=request.metric,
            start=start,
            end=end,
            snapshot=snapshot,
            warnings=warnings,
        )
        return EvidenceBundle(
            status="ok",
            current_store={"id": context.store_id},
            period=EvidencePeriodResult(start=start, end=end),
            metric=request.metric,
            unit=unit,
            calculation_version=version,
            result=result,
            coverage={
                "calendar_dates": calendar_dates,
                "recorded_dates": snapshot.recorded_dates,
            },
            comparison=None,
            warnings=warnings,
            truncated=False,
            summary=summary,
        )

    async def _read_snapshot(
        self,
        *,
        context: RuntimeContext,
        start: date,
        end: date,
        metric: EvidenceMetric,
    ) -> Snapshot:
        async with self._session_factory() as session:
            daily_scope = (
                StoreDailyRecord.store_id == context.store_id,
                StoreDailyRecord.date >= start,
                StoreDailyRecord.date <= end,
            )
            operating_scope = (
                *daily_scope,
                StoreDailyRecord.is_open.in_(("营业", "提前休息")),
            )
            daily_revenue = (
                select(func.coalesce(func.sum(StoreDailyRecord.daily_revenue), 0))
                .where(*daily_scope)
                .scalar_subquery()
            )
            operating_revenue = (
                select(func.coalesce(func.sum(StoreDailyRecord.daily_revenue), 0))
                .where(*operating_scope)
                .scalar_subquery()
            )
            operating_days = (
                select(func.count(distinct(StoreDailyRecord.date)))
                .where(*operating_scope)
                .scalar_subquery()
            )
            recorded_dates = (
                select(func.count(distinct(StoreDailyRecord.date)))
                .where(*daily_scope)
                .scalar_subquery()
            )
            if metric in {
                EvidenceMetric.MONTHLY_TOTAL_REVENUE,
                EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME,
                EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME,
            }:
                first_overlapping_month = start.replace(day=1)
                last_overlapping_month = end.replace(day=1)
                confirmed_settlement = (
                    select(func.coalesce(func.sum(SettlementRecord.amount), 0))
                    .where(
                        SettlementRecord.store_id == context.store_id,
                        SettlementRecord.status == "confirmed",
                        SettlementRecord.opening_month >= first_overlapping_month,
                        SettlementRecord.opening_month <= last_overlapping_month,
                    )
                    .scalar_subquery()
                )
            else:
                confirmed_settlement = literal(0)
            row = (
                await session.execute(
                    select(
                        daily_revenue.label("daily_revenue"),
                        operating_revenue.label("operating_revenue"),
                        operating_days.label("operating_days"),
                        confirmed_settlement.label("confirmed_settlement"),
                        recorded_dates.label("recorded_dates"),
                    )
                )
            ).one()

            categories: list[dict[str, object]] = []
            if metric in {
                EvidenceMetric.INCOME_CATEGORY_AMOUNT,
                EvidenceMetric.OTHER_DATA_AMOUNT,
            }:
                include_in_total = metric == EvidenceMetric.INCOME_CATEGORY_AMOUNT
                category_rows = (
                    await session.execute(
                        select(
                            DailyIncomeItem.category_id,
                            DailyIncomeItem.category_name,
                            DailyIncomeItem.include_in_total,
                            DailyIncomeItem.sort_order,
                            func.coalesce(func.sum(DailyIncomeItem.amount), 0).label("amount"),
                        )
                        .join(
                            StoreDailyRecord,
                            StoreDailyRecord.id == DailyIncomeItem.record_id,
                        )
                        .where(
                            *daily_scope,
                            DailyIncomeItem.include_in_total.is_(include_in_total),
                        )
                        .group_by(
                            DailyIncomeItem.category_id,
                            DailyIncomeItem.category_name,
                            DailyIncomeItem.include_in_total,
                            DailyIncomeItem.sort_order,
                        )
                        .order_by(
                            DailyIncomeItem.sort_order,
                            DailyIncomeItem.category_id,
                            DailyIncomeItem.category_name,
                        )
                    )
                ).all()
                categories = [
                    {
                        "category_id": int(category.category_id),
                        "category_name": category.category_name,
                        "include_in_total": bool(category.include_in_total),
                        "sort_order": int(category.sort_order),
                        "amount": int(category.amount),
                    }
                    for category in category_rows
                ]

        return Snapshot(
            daily_revenue=int(row.daily_revenue),
            operating_revenue=int(row.operating_revenue),
            operating_days=int(row.operating_days),
            confirmed_settlement=int(row.confirmed_settlement),
            recorded_dates=int(row.recorded_dates),
            categories=categories,
        )

    def _metric_result(
        self,
        *,
        metric: EvidenceMetric,
        start: date,
        end: date,
        snapshot: Snapshot,
        warnings: list[str],
    ) -> tuple[dict[str, object], str, str, str]:
        period = f"{start.isoformat()} 至 {end.isoformat()}"
        warning_text = "".join(warnings)
        if metric == EvidenceMetric.MONTHLY_TOTAL_REVENUE:
            total = snapshot.daily_revenue + snapshot.confirmed_settlement
            return (
                {
                    "daily_ledger_revenue": snapshot.daily_revenue,
                    "confirmed_settlement_income": snapshot.confirmed_settlement,
                    "monthly_total_revenue": total,
                },
                "EUR",
                "monthly_total_revenue.v1",
                (
                    f"{period} 的月度总收入为 {total} 欧元，"
                    f"其中每日台账营业额 {snapshot.daily_revenue} 欧元，"
                    f"已确认公司结算收入 {snapshot.confirmed_settlement} 欧元。"
                    f"{warning_text}"
                ),
            )
        if metric == EvidenceMetric.DAILY_LEDGER_REVENUE:
            return (
                {"daily_ledger_revenue": snapshot.daily_revenue},
                "EUR",
                "daily_ledger_revenue.v1",
                f"{period} 的每日台账营业额为 {snapshot.daily_revenue} 欧元。{warning_text}",
            )
        if metric == EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME:
            return (
                {"confirmed_settlement_income": snapshot.confirmed_settlement},
                "EUR",
                "confirmed_settlement_income.v1",
                (
                    f"{period} 重叠开票月份的已确认公司结算收入为 "
                    f"{snapshot.confirmed_settlement} 欧元。{warning_text}"
                ),
            )
        if metric == EvidenceMetric.OPERATING_DAYS:
            return (
                {"operating_days": snapshot.operating_days},
                "day",
                "operating_days.v1",
                (
                    f"{period} 有 {snapshot.operating_days} 个经营日；"
                    f"营业和提前休息计入，休息不计入。{warning_text}"
                ),
            )
        if metric == EvidenceMetric.OPERATING_DAY_AVERAGE_LEDGER_REVENUE:
            average = _rounded_average(snapshot.operating_revenue, snapshot.operating_days)
            if average is None:
                warnings.append("所选期间没有经营日，经营日均台账营业额不可用。")
                summary = (
                    f"{period} 没有经营日，经营日均台账营业额不可用；"
                    f"该指标不包含公司结算收入。{''.join(warnings)}"
                )
            else:
                summary = (
                    f"{period} 的经营日均台账营业额为 {average} 欧元/经营日"
                    f"（每日台账营业额 {snapshot.operating_revenue} 欧元 / "
                    f"经营日 {snapshot.operating_days}）；不包含公司结算收入。"
                    f"{warning_text}"
                )
            return (
                {
                    "daily_ledger_revenue": snapshot.operating_revenue,
                    "operating_days": snapshot.operating_days,
                    "operating_day_average_ledger_revenue": average,
                },
                "EUR/operating_day",
                "operating_day_average_ledger_revenue.v1",
                summary,
            )
        if metric == EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME:
            total = snapshot.daily_revenue + snapshot.confirmed_settlement
            average = _rounded_average(total, snapshot.operating_days)
            if average is None:
                warnings.append("该月没有经营日，月度日均收入不可用。")
                summary = f"{period} 没有经营日，月度日均收入不可用。{''.join(warnings)}"
            else:
                summary = (
                    f"{period} 的月度日均收入为 {average} 欧元/经营日"
                    f"（月度总收入 {total} 欧元 / 经营日 "
                    f"{snapshot.operating_days}）。{warning_text}"
                )
            return (
                {
                    "daily_ledger_revenue": snapshot.daily_revenue,
                    "confirmed_settlement_income": snapshot.confirmed_settlement,
                    "monthly_total_revenue": total,
                    "operating_days": snapshot.operating_days,
                    "monthly_daily_average_income": average,
                },
                "EUR/operating_day",
                "monthly_daily_average_income.v1",
                summary,
            )
        if metric in {
            EvidenceMetric.INCOME_CATEGORY_AMOUNT,
            EvidenceMetric.OTHER_DATA_AMOUNT,
        }:
            total = sum(int(category["amount"]) for category in snapshot.categories)
            label = (
                "收入分类金额"
                if metric == EvidenceMetric.INCOME_CATEGORY_AMOUNT
                else "其他数据金额"
            )
            details = "、".join(
                f"{category['category_name']} {category['amount']} 欧元"
                for category in snapshot.categories
            )
            detail_text = f"；按每日台账历史快照为：{details}" if details else ""
            version = (
                "income_category_amount.v1"
                if metric == EvidenceMetric.INCOME_CATEGORY_AMOUNT
                else "other_data_amount.v1"
            )
            return (
                {"amount": total, "categories": snapshot.categories},
                "EUR",
                version,
                f"{period} 的{label}为 {total} 欧元{detail_text}。{warning_text}",
            )
        raise ValueError("Unsupported evidence metric")

    def _resolve_period(
        self,
        period: object,
        context: RuntimeContext,
    ) -> tuple[date, date]:
        today = self._now(ZoneInfo(context.store_timezone)).date()
        if isinstance(period, CalendarMonthPeriod):
            start = date(period.year, period.month, 1)
            if start > today:
                raise ValueError("Future calendar months are not supported")
            return start, min(_month_end(start), today)
        return today.replace(day=1), today

    def _require_natural_month_period(
        self,
        start: date,
        end: date,
        context: RuntimeContext,
    ) -> None:
        today = self._now(ZoneInfo(context.store_timezone)).date()
        expected_end = min(_month_end(start), today)
        if start.day != 1 or end != expected_end or start.month != end.month:
            raise ValueError(
                "Monthly daily average income requires one natural month, "
                "using today as the current-month endpoint"
            )


def _month_end(start: date) -> date:
    if start.month == 12:
        following_month = date(start.year + 1, 1, 1)
    else:
        following_month = date(start.year, start.month + 1, 1)
    return date.fromordinal(following_month.toordinal() - 1)


def _rounded_average(total: int, count: int) -> int | None:
    if count == 0:
        return None
    return int((Decimal(total) / Decimal(count)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _is_temporary_sqlite_failure(error: OperationalError) -> bool:
    message = str(error.orig).lower()
    return "locked" in message or "busy" in message
