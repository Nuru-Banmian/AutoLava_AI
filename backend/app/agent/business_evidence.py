from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import case, distinct, func, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import (
    CalendarMonthPeriod,
    EvidenceBundle,
    EvidenceMetric,
    EvidencePeriodResult,
    EvidencePlan,
    SettlementDetailsEvidenceBundle,
    SettlementDetailsRequest,
)
from app.agent.runtime import RuntimeContext
from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
Now = Callable[[ZoneInfo], datetime]
MAX_SETTLEMENT_ROWS = 50


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
    ) -> EvidenceBundle | SettlementDetailsEvidenceBundle:
        request = plan.requests[0]
        if isinstance(request, SettlementDetailsRequest):
            return await self._collect_settlement_details(request, context)
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

    async def _collect_settlement_details(
        self,
        request: SettlementDetailsRequest,
        context: RuntimeContext,
    ) -> SettlementDetailsEvidenceBundle:
        start, end = self._resolve_period(request.period, context)
        empty_result = {
            "companies": [],
            "records": [],
            "pending_amount": 0,
            "confirmed_amount": 0,
            "pending_records": 0,
            "confirmed_records": 0,
        }
        if not context.features.company_settlement_enabled:
            message = "当前门店未启用公司结算，不能查询结算公司或开票记录明细。"
            return SettlementDetailsEvidenceBundle(
                status="refused",
                current_store={"id": context.store_id},
                period={"start": start, "end": end},
                result=empty_result,
                warnings=[message],
                summary=message,
            )

        for attempt in range(2):
            try:
                snapshot = await self._read_settlement_snapshot(
                    context=context,
                    request=request,
                    start=start,
                    end=end,
                )
                break
            except OperationalError as error:
                if attempt == 1 or not _is_temporary_sqlite_failure(error):
                    raise

        if not snapshot["settlement_enabled"]:
            message = "当前门店未启用公司结算，不能查询结算公司或开票记录明细。"
            return SettlementDetailsEvidenceBundle(
                status="refused",
                current_store={"id": context.store_id},
                period={"start": start, "end": end},
                result=empty_result,
                warnings=[message],
                summary=message,
            )
        if request.company_name is not None and not snapshot["company_match"]:
            choices = "、".join(company.name for company in snapshot["companies"])
            message = f"当前门店没有名为「{request.company_name}」的结算公司。"
            if choices:
                message += f"可选结算公司：{choices}。"
            return SettlementDetailsEvidenceBundle(
                status="ok",
                current_store={"id": context.store_id},
                period={"start": start, "end": end},
                result=empty_result,
                warnings=[message],
                truncated=snapshot["companies_truncated"],
                summary=message,
            )

        company_totals = snapshot["company_totals"]
        companies = [
            {
                "name": company.name,
                "is_active": company.is_active,
                "pending_amount": company_totals.get(company.id, {}).get("pending_amount", 0),
                "confirmed_amount": company_totals.get(company.id, {}).get(
                    "confirmed_amount", 0
                ),
                "record_count": company_totals.get(company.id, {}).get("record_count", 0),
            }
            for company in snapshot["selected_companies"]
        ]
        records = [
            {
                "company_name": record.company_name,
                "opening_month": record.opening_month,
                "amount": record.amount,
                "status": record.status,
            }
            for record in snapshot["records"]
        ]
        aggregate = snapshot["aggregate"]
        truncated = snapshot["companies_truncated"] or snapshot["records_truncated"]
        warnings = ["结果过多，仅返回前 50 项；金额合计仍覆盖完整筛选范围。"] if truncated else []
        summary = _settlement_summary(
            start=start,
            end=end,
            companies=companies,
            records=records,
            pending_amount=int(aggregate.pending_amount),
            confirmed_amount=int(aggregate.confirmed_amount),
            pending_records=int(aggregate.pending_records),
            confirmed_records=int(aggregate.confirmed_records),
            warnings=warnings,
        )
        return SettlementDetailsEvidenceBundle(
            status="ok",
            current_store={"id": context.store_id},
            period={"start": start, "end": end},
            result={
                "companies": companies,
                "records": records,
                "pending_amount": int(aggregate.pending_amount),
                "confirmed_amount": int(aggregate.confirmed_amount),
                "pending_records": int(aggregate.pending_records),
                "confirmed_records": int(aggregate.confirmed_records),
            },
            warnings=warnings,
            truncated=truncated,
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

    async def _read_settlement_snapshot(
        self,
        *,
        context: RuntimeContext,
        request: SettlementDetailsRequest,
        start: date,
        end: date,
    ) -> dict[str, object]:
        first_month = start.replace(day=1)
        last_month = end.replace(day=1)
        async with self._session_factory() as session:
            settlement_enabled = await session.scalar(
                select(Store.company_settlement_enabled).where(
                    Store.id == context.store_id,
                    Store.is_active.is_(True),
                )
            )
            if settlement_enabled is not True:
                return {"settlement_enabled": False}
            companies = list(
                (
                    await session.scalars(
                        select(SettlementCompany)
                        .where(SettlementCompany.store_id == context.store_id)
                        .order_by(
                            SettlementCompany.normalized_name,
                            SettlementCompany.id,
                        )
                        .limit(MAX_SETTLEMENT_ROWS + 1)
                    )
                ).all()
            )
            companies_truncated = len(companies) > MAX_SETTLEMENT_ROWS
            companies = companies[:MAX_SETTLEMENT_ROWS]

            selected_companies = companies
            company_match = True
            record_scope = [
                SettlementRecord.store_id == context.store_id,
                SettlementRecord.opening_month >= first_month,
                SettlementRecord.opening_month <= last_month,
            ]
            if request.company_name is not None:
                matching_companies = list(
                    (
                        await session.scalars(
                            select(SettlementCompany)
                            .where(
                                SettlementCompany.store_id == context.store_id,
                                SettlementCompany.normalized_name
                                == request.company_name.casefold(),
                            )
                            .order_by(SettlementCompany.id)
                        )
                    ).all()
                )
                company_match = bool(matching_companies)
                selected_companies = matching_companies[:MAX_SETTLEMENT_ROWS]
                matching_ids = [company.id for company in matching_companies]
                record_scope.append(SettlementRecord.company_id.in_(matching_ids or [-1]))
            if request.status is not None:
                record_scope.append(SettlementRecord.status == request.status)

            aggregate = (
                await session.execute(
                    select(
                        func.coalesce(
                            func.sum(
                                case(
                                    (SettlementRecord.status == "pending", SettlementRecord.amount),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("pending_amount"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        SettlementRecord.status == "confirmed",
                                        SettlementRecord.amount,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("confirmed_amount"),
                        func.count(
                            case((SettlementRecord.status == "pending", 1))
                        ).label("pending_records"),
                        func.count(
                            case((SettlementRecord.status == "confirmed", 1))
                        ).label("confirmed_records"),
                    ).where(*record_scope)
                )
            ).one()
            grouped_totals = (
                await session.execute(
                    select(
                        SettlementRecord.company_id,
                        func.coalesce(
                            func.sum(
                                case(
                                    (SettlementRecord.status == "pending", SettlementRecord.amount),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("pending_amount"),
                        func.coalesce(
                            func.sum(
                                case(
                                    (
                                        SettlementRecord.status == "confirmed",
                                        SettlementRecord.amount,
                                    ),
                                    else_=0,
                                )
                            ),
                            0,
                        ).label("confirmed_amount"),
                        func.count().label("record_count"),
                    )
                    .where(*record_scope)
                    .group_by(SettlementRecord.company_id)
                )
            ).all()
            company_totals = {
                row.company_id: {
                    "pending_amount": int(row.pending_amount),
                    "confirmed_amount": int(row.confirmed_amount),
                    "record_count": int(row.record_count),
                }
                for row in grouped_totals
            }
            records = list(
                (
                    await session.scalars(
                        select(SettlementRecord)
                        .where(*record_scope)
                        .order_by(
                            SettlementRecord.opening_month.desc(),
                            SettlementRecord.status.desc(),
                            func.lower(SettlementRecord.company_name),
                            SettlementRecord.id,
                        )
                        .limit(MAX_SETTLEMENT_ROWS + 1)
                    )
                ).all()
            )
        return {
            "settlement_enabled": True,
            "companies": companies,
            "companies_truncated": companies_truncated,
            "selected_companies": selected_companies,
            "company_match": company_match,
            "aggregate": aggregate,
            "company_totals": company_totals,
            "records": records[:MAX_SETTLEMENT_ROWS],
            "records_truncated": len(records) > MAX_SETTLEMENT_ROWS,
        }

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


def _settlement_summary(
    *,
    start: date,
    end: date,
    companies: list[dict[str, object]],
    records: list[dict[str, object]],
    pending_amount: int,
    confirmed_amount: int,
    pending_records: int,
    confirmed_records: int,
    warnings: list[str],
) -> str:
    headline = (
        f"{start.isoformat()} 至 {end.isoformat()} 的公司结算明细："
        f"待到账 {pending_amount} 欧元（{pending_records} 笔），"
        f"已确认 {confirmed_amount} 欧元（{confirmed_records} 笔）。"
    )
    if companies:
        company_text = "；".join(
            (
                f"{company['name']}（{'使用中' if company['is_active'] else '已归档'}，"
                f"待到账 {company['pending_amount']} 欧元，"
                f"已确认 {company['confirmed_amount']} 欧元，"
                f"{company['record_count']} 笔）"
            )
            for company in companies
        )
        headline += f"结算公司：{company_text}。"
    if records:
        status_labels = {"pending": "待到账", "confirmed": "已确认"}
        record_text = "；".join(
            (
                f"{record['opening_month'].isoformat()[:7]} · "
                f"{record['company_name']} · "
                f"{status_labels[str(record['status'])]} {record['amount']} 欧元"
            )
            for record in records
        )
        headline += f"开票记录：{record_text}。"
    else:
        headline += "所选期间没有开票记录。"
    return headline + "".join(warnings)


def _is_temporary_sqlite_failure(error: OperationalError) -> bool:
    message = str(error.orig).lower()
    return "locked" in message or "busy" in message
