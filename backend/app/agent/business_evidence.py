from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import distinct, func, select
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
from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementRecord

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
Now = Callable[[ZoneInfo], datetime]


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
        if request.metric != EvidenceMetric.MONTHLY_TOTAL_REVENUE:
            raise ValueError("Unsupported evidence metric")
        start, end = self._resolve_period(request.period, context)
        for attempt in range(2):
            try:
                row = await self._read_snapshot(
                    context=context,
                    start=start,
                    end=end,
                )
                break
            except OperationalError as error:
                if attempt == 1 or not _is_temporary_sqlite_failure(error):
                    raise

        daily_amount = int(row.daily_revenue)
        settlement_amount = int(row.confirmed_settlement)
        total = daily_amount + settlement_amount
        calendar_dates = (end - start).days + 1
        missing_dates = calendar_dates - int(row.recorded_dates)
        warnings = (
            [
                f"所选期间有 {missing_dates} 个日期没有每日台账；"
                "这不表示门店本应营业。"
            ]
            if missing_dates
            else []
        )
        summary = (
            f"{start.isoformat()} 至 {end.isoformat()} 的月度总收入为 {total} 欧元，"
            f"其中每日台账营业额 {daily_amount} 欧元，"
            f"已确认公司结算收入 {settlement_amount} 欧元。"
            + "".join(warnings)
        )
        return EvidenceBundle(
            status="ok",
            current_store={"id": context.store_id},
            period=EvidencePeriodResult(start=start, end=end),
            metric=EvidenceMetric.MONTHLY_TOTAL_REVENUE,
            unit="EUR",
            calculation_version="monthly_total_revenue.v1",
            result={
                "daily_ledger_revenue": daily_amount,
                "confirmed_settlement_income": settlement_amount,
                "monthly_total_revenue": total,
            },
            coverage={
                "calendar_dates": calendar_dates,
                "recorded_dates": int(row.recorded_dates),
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
    ):
        async with self._session_factory() as session:
            daily_scope = (
                StoreDailyRecord.store_id == context.store_id,
                StoreDailyRecord.date >= start,
                StoreDailyRecord.date <= end,
            )
            daily_revenue = (
                select(func.coalesce(func.sum(StoreDailyRecord.daily_revenue), 0))
                .where(*daily_scope)
                .scalar_subquery()
            )
            recorded_dates = (
                select(func.count(distinct(StoreDailyRecord.date)))
                .where(*daily_scope)
                .scalar_subquery()
            )
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
            row = (
                await session.execute(
                    select(
                        daily_revenue.label("daily_revenue"),
                        confirmed_settlement.label("confirmed_settlement"),
                        recorded_dates.label("recorded_dates"),
                    )
                )
            ).one()
        return row

    def _resolve_period(
        self,
        period: object,
        context: RuntimeContext,
    ) -> tuple[date, date]:
        if isinstance(period, CalendarMonthPeriod):
            start = date(period.year, period.month, 1)
            return start, _month_end(start)
        today = self._now(ZoneInfo(context.store_timezone)).date()
        return today.replace(day=1), today


def _month_end(start: date) -> date:
    if start.month == 12:
        following_month = date(start.year + 1, 1, 1)
    else:
        following_month = date(start.year, start.month + 1, 1)
    return date.fromordinal(following_month.toordinal() - 1)


def _is_temporary_sqlite_failure(error: OperationalError) -> bool:
    message = str(error.orig).lower()
    return "locked" in message or "busy" in message
