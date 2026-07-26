from collections import defaultdict
from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal
import unicodedata
from zoneinfo import ZoneInfo

from sqlalchemy import case, distinct, exists, func, literal, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agent.contracts import (
    CalendarMonthPeriod,
    CalendarYearPeriod,
    CustomDateRangePeriod,
    DailyLedgerAmount,
    DailyLedgerFacts,
    DailyLedgerRequest,
    DailyLedgerResult,
    DailyLedgerExtremeResult,
    EvidenceBundle,
    EvidenceComparisonResult,
    EvidenceFilters,
    EvidenceGroup,
    EvidenceGroupRow,
    EvidenceMetric,
    EvidencePeriodResult,
    EvidencePlan,
    GroupedMetricResult,
    SettlementDetailsEvidenceBundle,
    SettlementDetailsRequest,
    UntrustedRawEvent,
    ExactDatePeriod,
    MonthlyTotalRevenueResult,
    PreviousMonthPeriod,
    PreviousMonthToDatePeriod,
)
from app.agent.runtime import RuntimeContext
from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
Now = Callable[[ZoneInfo], datetime]
MAX_SETTLEMENT_ROWS = 50
MAX_GROUP_ROWS = 400
WEEKDAY_DATABASE_VALUES = {
    "星期一": "1",
    "星期二": "2",
    "星期三": "3",
    "星期四": "4",
    "星期五": "5",
    "星期六": "6",
    "星期日": "0",
}


class EvidenceClarificationError(ValueError):
    """A safe, user-resolvable evidence request that must end in clarification."""


@dataclass(frozen=True)
class Snapshot:
    daily_revenue: int
    operating_revenue: int
    operating_days: int
    confirmed_settlement: int
    recorded_dates: int
    recorded_date_values: list[date]
    weather_recorded_dates: int
    missing_weather_dates: list[date]
    wash_count: int
    wash_count_recorded_operating_days: int
    wash_count_missing_dates: list[date]
    wash_count_revenue: int
    category_total_mismatches: list[dict[str, object]]
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
    ) -> EvidenceBundle | SettlementDetailsEvidenceBundle:
        request = plan.requests[0]
        if isinstance(request, SettlementDetailsRequest):
            return await self._collect_settlement_details(request, context)
        if isinstance(request, DailyLedgerRequest):
            return await self._collect_daily_ledger(request.date, context)
        start, end = self._resolve_period(request.period, context)
        if request.metric == EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME:
            self._require_natural_month_period(start, end, context)
        category_ids = await self._resolve_category_filter(request.filters, context)
        comparison_period = (
            self._resolve_period(request.comparison.period, context)
            if request.comparison is not None
            else None
        )
        comparison_snapshot: Snapshot | None = None
        category_metric_group = (
            request.group_by == EvidenceGroup.INCOME_CATEGORY
            and request.metric
            in {
                EvidenceMetric.INCOME_CATEGORY_AMOUNT,
                EvidenceMetric.OTHER_DATA_AMOUNT,
            }
        )
        if request.group_by is not None and not category_metric_group:
            rows, recorded_dates, truncated = await self._read_grouped_snapshot(
                context=context,
                start=start,
                end=end,
                metric=request.metric,
                group_by=request.group_by,
                filters=request.filters,
                category_ids=category_ids,
            )
            warnings = (
                ["结果过多，仅返回前 400 个分组。"] if truncated else []
            )
            summary = _grouped_summary(
                start=start,
                end=end,
                group_by=request.group_by,
                rows=rows,
                warnings=warnings,
            )
            return EvidenceBundle(
                status="ok",
                current_store={"id": context.store_id},
                period=EvidencePeriodResult(start=start, end=end),
                metric=request.metric,
                group_by=request.group_by,
                filters=request.filters,
                unit=_metric_unit(request.metric),
                calculation_version="grouped_business_metric.v1",
                result=GroupedMetricResult(group_by=request.group_by, rows=rows),
                coverage={
                    "calendar_dates": (end - start).days + 1,
                    "recorded_dates": recorded_dates,
                },
                warnings=warnings,
                truncated=truncated,
                summary=summary,
            )
        if request.extreme is not None:
            result, recorded_dates = await self._read_daily_extreme(
                context=context,
                start=start,
                end=end,
                extreme=request.extreme,
                filters=request.filters,
                category_ids=category_ids,
            )
            summary = _extreme_summary(start=start, end=end, result=result)
            return EvidenceBundle(
                status="ok",
                current_store={"id": context.store_id},
                period=EvidencePeriodResult(start=start, end=end),
                metric=request.metric,
                filters=request.filters,
                extreme=request.extreme,
                unit="EUR",
                calculation_version="daily_ledger_extreme.v1",
                result=result,
                coverage={
                    "calendar_dates": (end - start).days + 1,
                    "recorded_dates": recorded_dates,
                },
                warnings=[],
                truncated=False,
                summary=summary,
            )
        for attempt in range(2):
            try:
                snapshot = await self._read_snapshot(
                    context=context,
                    start=start,
                    end=end,
                    metric=request.metric,
                    filters=request.filters,
                    category_ids=category_ids,
                )
                if comparison_period is not None:
                    comparison_snapshot = await self._read_snapshot(
                        context=context,
                        start=comparison_period[0],
                        end=comparison_period[1],
                        metric=request.metric,
                        filters=None,
                        category_ids=frozenset(),
                    )
                break
            except OperationalError as error:
                if attempt == 1 or not _is_temporary_sqlite_failure(error):
                    raise

        calendar_dates = (end - start).days + 1
        recorded_date_set = set(snapshot.recorded_date_values)
        unrecorded_dates = (
            [
                date.fromordinal(ordinal)
                for ordinal in range(start.toordinal(), end.toordinal() + 1)
                if date.fromordinal(ordinal) not in recorded_date_set
            ]
            if request.filters is None
            else []
        )
        if snapshot.operating_days:
            wash_count_coverage_percent = _rounded_average(
                snapshot.wash_count_recorded_operating_days * 100,
                snapshot.operating_days,
            )
        else:
            wash_count_coverage_percent = None
        wash_count_sufficient = (
            context.features.wash_count_enabled
            and snapshot.operating_days > 0
            and not snapshot.wash_count_missing_dates
        )
        warnings: list[str] = []
        if unrecorded_dates:
            warnings.append(
                f"所选期间有 {len(unrecorded_dates)} 个日期没有每日台账；"
                "这只表示没有记录，不表示门店本应营业，也不推断记录起始日期。"
            )
        if snapshot.missing_weather_dates:
            warnings.append(
                f"有 {len(snapshot.missing_weather_dates)} 个每日台账缺少记录天气。"
            )
        if context.features.wash_count_enabled and snapshot.wash_count_missing_dates:
            warnings.append(
                f"洗车数量覆盖 {snapshot.wash_count_recorded_operating_days}/"
                f"{snapshot.operating_days} 个经营日"
                f"（{wash_count_coverage_percent}%）；缺失没有按零计算。"
            )
        if snapshot.category_total_mismatches:
            warnings.append(
                f"有 {len(snapshot.category_total_mismatches)} 个分类记账的"
                "计入总额分类合计与每日台账营业额不一致。"
            )
        if request.filters is not None:
            warnings.append(f"筛选后匹配 {snapshot.recorded_dates} 个每日台账日期。")
        result, unit, version, summary = self._metric_result(
            metric=request.metric,
            start=start,
            end=end,
            snapshot=snapshot,
            warnings=warnings,
            wash_count_enabled=context.features.wash_count_enabled,
            wash_count_sufficient=wash_count_sufficient,
        )
        comparison: EvidenceComparisonResult | None = None
        if (
            request.comparison is not None
            and comparison_period is not None
            and comparison_snapshot is not None
        ):
            comparison, comparison_summary, comparison_warnings = (
                self._comparison_result(
                    current=snapshot,
                    current_days=calendar_dates,
                    comparison=comparison_snapshot,
                    comparison_period=comparison_period,
                    include_percentage=request.comparison.include_percentage,
                )
            )
            warnings.extend(comparison_warnings)
            summary += comparison_summary + "".join(comparison_warnings)
        return EvidenceBundle(
            status="ok",
            current_store={"id": context.store_id},
            period=EvidencePeriodResult(start=start, end=end),
            metric=request.metric,
            group_by=request.group_by,
            filters=request.filters,
            unit=unit,
            calculation_version=version,
            result=result,
            coverage={
                "calendar_dates": calendar_dates,
                "recorded_dates": snapshot.recorded_dates,
            },
            completeness={
                "status": (
                    "limited"
                    if (
                        unrecorded_dates
                        or snapshot.missing_weather_dates
                        or (
                            context.features.wash_count_enabled
                            and snapshot.wash_count_missing_dates
                        )
                        or snapshot.category_total_mismatches
                    )
                    else "sufficient"
                ),
                "unrecorded_dates": unrecorded_dates,
                "missing_weather_dates": snapshot.missing_weather_dates,
                "wash_count_enabled": context.features.wash_count_enabled,
                "operating_days": snapshot.operating_days,
                "wash_count_recorded_operating_days": (
                    snapshot.wash_count_recorded_operating_days
                ),
                "wash_count_missing_dates": snapshot.wash_count_missing_dates,
                "wash_count_coverage_percent": wash_count_coverage_percent,
                "wash_count_sufficient": wash_count_sufficient,
                "category_total_mismatches": snapshot.category_total_mismatches,
            },
            comparison=comparison,
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

    async def _collect_daily_ledger(
        self,
        target: date,
        context: RuntimeContext,
    ) -> EvidenceBundle:
        for attempt in range(2):
            try:
                record = await self._read_daily_ledger_snapshot(
                    context=context,
                    target=target,
                )
                break
            except OperationalError as error:
                if attempt == 1 or not _is_temporary_sqlite_failure(error):
                    raise

        if record is None:
            warning = (
                f"{target.isoformat()} 没有每日台账；"
                "这是未记录状态，不表示零收入或休息。"
            )
            return EvidenceBundle(
                status="not_recorded",
                current_store={"id": context.store_id},
                period=EvidencePeriodResult(start=target, end=target),
                metric=EvidenceMetric.DAILY_LEDGER,
                unit="mixed",
                calculation_version="daily_ledger.v1",
                result=DailyLedgerResult(
                    facts=None,
                    missing_fields=[],
                    unavailable_fields=[],
                    raw_event=None,
                ),
                coverage={"calendar_dates": 1, "recorded_dates": 0},
                comparison=None,
                warnings=[warning],
                truncated=False,
                summary=warning,
            )

        sorted_items = sorted(
            record.items,
            key=lambda item: (
                item.sort_order,
                item.category_name.casefold(),
                item.id,
            ),
        )
        income_categories = [
            DailyLedgerAmount(name=item.category_name, amount=item.amount)
            for item in sorted_items
            if item.include_in_total
        ]
        other_data = [
            DailyLedgerAmount(name=item.category_name, amount=item.amount)
            for item in sorted_items
            if not item.include_in_total
        ]
        raw_event = (
            UntrustedRawEvent(text=record.activity)
            if record.activity is not None and record.activity.strip()
            else None
        )
        missing_fields: list[Literal["recorded_weather", "wash_count"]] = []
        unavailable_fields: list[Literal["wash_count"]] = []
        if record.weather is None:
            missing_fields.append("recorded_weather")
        if context.features.wash_count_enabled:
            if record.wash_count is None:
                missing_fields.append("wash_count")
            wash_count = record.wash_count
        else:
            wash_count = None
            unavailable_fields.append("wash_count")
        facts = DailyLedgerFacts(
            date=record.date,
            daily_revenue=record.daily_revenue,
            income_mode=(
                "分类记账" if record.income_mode == "composed" else "总额记账"
            ),
            income_categories=income_categories,
            other_data=other_data,
            operating_status=record.is_open,
            recorded_weather=record.weather,
            wash_count=wash_count,
        )
        summary = _daily_ledger_summary(
            facts=facts,
            missing_fields=missing_fields,
            unavailable_fields=unavailable_fields,
            raw_event=raw_event,
        )
        return EvidenceBundle(
            status="ok",
            current_store={"id": context.store_id},
            period=EvidencePeriodResult(start=target, end=target),
            metric=EvidenceMetric.DAILY_LEDGER,
            unit="mixed",
            calculation_version="daily_ledger.v1",
            result=DailyLedgerResult(
                facts=facts,
                missing_fields=missing_fields,
                unavailable_fields=unavailable_fields,
                raw_event=raw_event,
            ),
            coverage={"calendar_dates": 1, "recorded_dates": 1},
            comparison=None,
            warnings=[],
            truncated=False,
            summary=summary,
        )

    async def _read_daily_ledger_snapshot(
        self,
        *,
        context: RuntimeContext,
        target: date,
    ) -> StoreDailyRecord | None:
        async with self._session_factory() as session:
            return await session.scalar(
                select(StoreDailyRecord)
                .where(
                    StoreDailyRecord.store_id == context.store_id,
                    StoreDailyRecord.date == target,
                )
                .options(selectinload(StoreDailyRecord.items))
            )

    async def _resolve_category_filter(
        self,
        filters: EvidenceFilters | None,
        context: RuntimeContext,
    ) -> frozenset[int]:
        if filters is None or not filters.income_categories:
            return frozenset()
        async with self._session_factory() as session:
            configured = (
                await session.execute(
                    select(IncomeCategory.id, IncomeCategory.name).where(
                        IncomeCategory.store_id == context.store_id
                    )
                )
            ).all()
            historical = (
                await session.execute(
                    select(DailyIncomeItem.category_id, DailyIncomeItem.category_name)
                    .join(
                        StoreDailyRecord,
                        StoreDailyRecord.id == DailyIncomeItem.record_id,
                    )
                    .where(StoreDailyRecord.store_id == context.store_id)
                    .distinct()
                )
            ).all()

        candidates: list[tuple[int, str]] = []
        seen_candidates: set[tuple[int, str]] = set()
        for category_id, name in [*configured, *historical]:
            candidate = (int(category_id), str(name).strip())
            if candidate[1] and candidate not in seen_candidates:
                candidates.append(candidate)
                seen_candidates.add(candidate)
        by_normalized: dict[str, set[int]] = defaultdict(set)
        for category_id, name in candidates:
            by_normalized[_normalize_category_name(name)].add(category_id)

        resolved: set[int] = set()
        unresolved: list[str] = []
        for requested in filters.income_categories:
            matches = by_normalized.get(_normalize_category_name(requested), set())
            if len(matches) == 1:
                resolved.update(matches)
            else:
                unresolved.append(requested)
        if unresolved:
            safe_names = sorted(
                {name for _, name in candidates},
                key=lambda value: (_normalize_category_name(value), value),
            )[:20]
            choices = "、".join(safe_names)
            requested = "、".join(f"「{name}」" for name in unresolved)
            message = f"无法在当前门店唯一确定收入分类 {requested}，请从候选项中选择。"
            if choices:
                message += f" 当前门店可选收入分类：{choices}。"
            else:
                message += " 当前门店暂无可选收入分类。"
            raise EvidenceClarificationError(message)
        return frozenset(resolved)

    async def _read_grouped_snapshot(
        self,
        *,
        context: RuntimeContext,
        start: date,
        end: date,
        metric: EvidenceMetric,
        group_by: EvidenceGroup,
        filters: EvidenceFilters | None,
        category_ids: frozenset[int],
    ) -> tuple[list[EvidenceGroupRow], int, bool]:
        async with self._session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(StoreDailyRecord)
                        .where(
                            StoreDailyRecord.store_id == context.store_id,
                            StoreDailyRecord.date >= start,
                            StoreDailyRecord.date <= end,
                            *_daily_filter_conditions(filters, category_ids),
                        )
                        .options(selectinload(StoreDailyRecord.items))
                        .order_by(StoreDailyRecord.date)
                    )
                )
                .unique()
                .all()
            )

        aggregates: dict[str, dict[str, object]] = {}
        if group_by == EvidenceGroup.INCOME_CATEGORY:
            include_in_total = metric != EvidenceMetric.OTHER_DATA_AMOUNT
            for record in records:
                for item in record.items:
                    if item.include_in_total != include_in_total:
                        continue
                    if category_ids and item.category_id not in category_ids:
                        continue
                    key = f"{item.category_id}:{item.category_name}"
                    aggregate = aggregates.setdefault(
                        key,
                        {
                            "label": item.category_name,
                            "value": 0,
                            "sort": (
                                item.sort_order,
                                item.category_id,
                                _normalize_category_name(item.category_name),
                            ),
                        },
                    )
                    aggregate["value"] = int(aggregate["value"]) + item.amount
        else:
            for record in records:
                key, label, sort_key = _record_group(record, group_by)
                aggregate = aggregates.setdefault(
                    key,
                    {
                        "label": label,
                        "daily_revenue": 0,
                        "operating_revenue": 0,
                        "operating_days": 0,
                        "category_amount": 0,
                        "sort": sort_key,
                    },
                )
                aggregate["daily_revenue"] = (
                    int(aggregate["daily_revenue"]) + record.daily_revenue
                )
                if record.is_open in {"营业", "提前休息"}:
                    aggregate["operating_revenue"] = (
                        int(aggregate["operating_revenue"]) + record.daily_revenue
                    )
                    aggregate["operating_days"] = int(aggregate["operating_days"]) + 1
                if metric in {
                    EvidenceMetric.INCOME_CATEGORY_AMOUNT,
                    EvidenceMetric.OTHER_DATA_AMOUNT,
                }:
                    include_in_total = metric == EvidenceMetric.INCOME_CATEGORY_AMOUNT
                    aggregate["category_amount"] = int(
                        aggregate["category_amount"]
                    ) + sum(
                        item.amount
                        for item in record.items
                        if item.include_in_total == include_in_total
                        and (not category_ids or item.category_id in category_ids)
                    )

        ordered = sorted(aggregates.items(), key=lambda item: item[1]["sort"])
        truncated = len(ordered) > MAX_GROUP_ROWS
        rows: list[EvidenceGroupRow] = []
        for key, aggregate in ordered[:MAX_GROUP_ROWS]:
            if group_by == EvidenceGroup.INCOME_CATEGORY:
                value = int(aggregate["value"])
            elif metric == EvidenceMetric.DAILY_LEDGER_REVENUE:
                value = int(aggregate["daily_revenue"])
            elif metric == EvidenceMetric.OPERATING_DAYS:
                value = int(aggregate["operating_days"])
            elif metric == EvidenceMetric.OPERATING_DAY_AVERAGE_LEDGER_REVENUE:
                value = _rounded_average(
                    int(aggregate["operating_revenue"]),
                    int(aggregate["operating_days"]),
                )
            else:
                value = int(aggregate["category_amount"])
            rows.append(
                EvidenceGroupRow(
                    key=key,
                    label=str(aggregate["label"]),
                    value=value,
                )
            )
        return rows, len(records), truncated

    async def _read_daily_extreme(
        self,
        *,
        context: RuntimeContext,
        start: date,
        end: date,
        extreme: Literal["highest", "lowest"],
        filters: EvidenceFilters | None,
        category_ids: frozenset[int],
    ) -> tuple[DailyLedgerExtremeResult, int]:
        async with self._session_factory() as session:
            records = list(
                (
                    await session.scalars(
                        select(StoreDailyRecord)
                        .where(
                            StoreDailyRecord.store_id == context.store_id,
                            StoreDailyRecord.date >= start,
                            StoreDailyRecord.date <= end,
                            StoreDailyRecord.is_open.in_(("营业", "提前休息")),
                            *_daily_filter_conditions(filters, category_ids),
                        )
                        .order_by(StoreDailyRecord.date)
                    )
                ).all()
            )
        if not records:
            return (
                DailyLedgerExtremeResult(
                    extreme=extreme,
                    daily_ledger_revenue=None,
                    dates=[],
                ),
                0,
            )
        values = [record.daily_revenue for record in records]
        target = max(values) if extreme == "highest" else min(values)
        return (
            DailyLedgerExtremeResult(
                extreme=extreme,
                daily_ledger_revenue=target,
                dates=[record.date for record in records if record.daily_revenue == target],
            ),
            len(records),
        )

    async def _read_snapshot(
        self,
        *,
        context: RuntimeContext,
        start: date,
        end: date,
        metric: EvidenceMetric,
        filters: EvidenceFilters | None = None,
        category_ids: frozenset[int] = frozenset(),
    ) -> Snapshot:
        async with self._session_factory() as session:
            daily_scope = (
                StoreDailyRecord.store_id == context.store_id,
                StoreDailyRecord.date >= start,
                StoreDailyRecord.date <= end,
                *_daily_filter_conditions(filters, category_ids),
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

            record_rows = (
                await session.execute(
                    select(
                        StoreDailyRecord.id,
                        StoreDailyRecord.date,
                        StoreDailyRecord.daily_revenue,
                        StoreDailyRecord.income_mode,
                        StoreDailyRecord.wash_count,
                        StoreDailyRecord.is_open,
                        StoreDailyRecord.weather,
                    )
                    .where(*daily_scope)
                    .order_by(StoreDailyRecord.date)
                )
            ).all()
            included_item_rows = (
                await session.execute(
                    select(
                        DailyIncomeItem.record_id,
                        func.coalesce(func.sum(DailyIncomeItem.amount), 0).label("amount"),
                    )
                    .join(
                        StoreDailyRecord,
                        StoreDailyRecord.id == DailyIncomeItem.record_id,
                    )
                    .where(*daily_scope, DailyIncomeItem.include_in_total.is_(True))
                    .group_by(DailyIncomeItem.record_id)
                )
            ).all()
            included_amounts = {
                int(item.record_id): int(item.amount) for item in included_item_rows
            }
            operating_records = [
                record for record in record_rows if record.is_open in {"营业", "提前休息"}
            ]
            wash_count_records = [
                record for record in operating_records if record.wash_count is not None
            ]
            missing_weather_dates = [
                record.date
                for record in record_rows
                if record.weather is None or not record.weather.strip()
            ]
            wash_count_missing_dates = [
                record.date for record in operating_records if record.wash_count is None
            ]
            category_total_mismatches = [
                {
                    "date": record.date,
                    "daily_ledger_revenue": int(record.daily_revenue),
                    "included_category_amount": included_amounts.get(int(record.id), 0),
                }
                for record in record_rows
                if record.income_mode == "composed"
                and included_amounts.get(int(record.id), 0) != int(record.daily_revenue)
            ]

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
                            *(
                                (DailyIncomeItem.category_id.in_(category_ids),)
                                if category_ids
                                else ()
                            ),
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
            recorded_date_values=[record.date for record in record_rows],
            weather_recorded_dates=len(record_rows) - len(missing_weather_dates),
            missing_weather_dates=missing_weather_dates,
            wash_count=sum(int(record.wash_count) for record in wash_count_records),
            wash_count_recorded_operating_days=len(wash_count_records),
            wash_count_missing_dates=wash_count_missing_dates,
            wash_count_revenue=sum(
                int(record.daily_revenue) for record in wash_count_records
            ),
            category_total_mismatches=category_total_mismatches,
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
        wash_count_enabled: bool,
        wash_count_sufficient: bool,
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
        if metric == EvidenceMetric.WASH_COUNT:
            if not wash_count_enabled:
                warnings.append(
                    "门店已关闭记录洗车数量；历史洗车数量保留但当前查询不可用。"
                )
                result = {"available": False, "wash_count": None}
                summary = f"{period} 的洗车数量不可用；门店已关闭记录洗车数量。"
            elif not wash_count_sufficient:
                warnings.append("洗车数量覆盖不足，洗车数量不可用。")
                result = {"available": False, "wash_count": None}
                summary = (
                    f"{period} 的洗车数量因经营日覆盖不足而不可用；"
                    "缺失没有按零计算。"
                )
            else:
                result = {"available": True, "wash_count": snapshot.wash_count}
                summary = f"{period} 的洗车数量为 {snapshot.wash_count} 辆。"
            return result, "car", "wash_count.v1", f"{summary}{''.join(warnings)}"
        if metric == EvidenceMetric.AVERAGE_REVENUE_PER_CAR:
            if not wash_count_enabled:
                warnings.append(
                    "门店已关闭记录洗车数量；历史数据保留但平均每车收入不可用。"
                )
                result = {
                    "available": False,
                    "daily_ledger_revenue": None,
                    "wash_count": None,
                    "average_revenue_per_car": None,
                }
                summary = f"{period} 的平均每车收入不可用；门店已关闭记录洗车数量。"
            elif not wash_count_sufficient:
                warnings.append("洗车数量覆盖不足，平均每车收入不可用。")
                result = {
                    "available": False,
                    "daily_ledger_revenue": None,
                    "wash_count": None,
                    "average_revenue_per_car": None,
                }
                summary = (
                    f"{period} 的平均每车收入因经营日覆盖不足而不可用；"
                    "缺失没有按零计算。"
                )
            elif snapshot.wash_count == 0:
                warnings.append("洗车数量合计为零，平均每车收入不可用。")
                result = {
                    "available": False,
                    "daily_ledger_revenue": snapshot.wash_count_revenue,
                    "wash_count": 0,
                    "average_revenue_per_car": None,
                }
                summary = (
                    f"{period} 同时记录洗车数量的经营日洗车数量合计为零，"
                    "平均每车收入不可用；不包含公司结算收入。"
                )
            else:
                average = _rounded_average(
                    snapshot.wash_count_revenue,
                    snapshot.wash_count,
                )
                result = {
                    "available": True,
                    "daily_ledger_revenue": snapshot.wash_count_revenue,
                    "wash_count": snapshot.wash_count,
                    "average_revenue_per_car": average,
                }
                summary = (
                    f"{period} 的平均每车收入为 {average} 欧元/车"
                    f"（同时记录洗车数量的经营日每日台账营业额 "
                    f"{snapshot.wash_count_revenue} 欧元 / 洗车数量 "
                    f"{snapshot.wash_count}）；不包含公司结算收入。"
                )
            return (
                result,
                "EUR/car",
                "average_revenue_per_car.v1",
                f"{summary}{''.join(warnings)}",
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

    def _comparison_result(
        self,
        *,
        current: Snapshot,
        current_days: int,
        comparison: Snapshot,
        comparison_period: tuple[date, date],
        include_percentage: bool,
    ) -> tuple[EvidenceComparisonResult, str, list[str]]:
        comparison_start, comparison_end = comparison_period
        comparison_days = (comparison_end - comparison_start).days + 1
        equal_length = comparison_days == current_days
        warnings: list[str] = []
        if comparison.recorded_dates == 0 and comparison.confirmed_settlement == 0:
            warning = (
                f"比较期间 {comparison_start.isoformat()} 至 "
                f"{comparison_end.isoformat()} 没有历史数据；仅描述当前期间。"
            )
            return (
                EvidenceComparisonResult(
                    status="no_data",
                    period=EvidencePeriodResult(
                        start=comparison_start,
                        end=comparison_end,
                    ),
                    result=None,
                    amount_difference=None,
                    percentage_change=None,
                    percentage_status="unavailable_no_data",
                    equal_length=equal_length,
                ),
                "",
                [warning],
            )

        current_total = current.daily_revenue + current.confirmed_settlement
        comparison_total = comparison.daily_revenue + comparison.confirmed_settlement
        amount_difference = current_total - comparison_total
        percentage_change: float | None = None
        percentage_status: Literal[
            "not_requested",
            "available",
            "unavailable_zero_baseline",
        ] = "not_requested"
        if include_percentage:
            if comparison_total == 0:
                percentage_status = "unavailable_zero_baseline"
                warnings.append("比较基准为 0 欧元，百分比不可用。")
            else:
                percentage_status = "available"
                percentage_change = round(
                    amount_difference / comparison_total * 100,
                    2,
                )
        summary = (
            f"比较期间 {comparison_start.isoformat()} 至 "
            f"{comparison_end.isoformat()} 的月度总收入为 "
            f"{comparison_total} 欧元，金额差为 {amount_difference} 欧元。"
        )
        if percentage_change is not None:
            summary += f"百分比变化为 {percentage_change:g}%。"
        if not equal_length:
            suffix = "百分比仅供参考。" if include_percentage else "默认仅提供金额差。"
            warnings.append(
                f"期间长度不同（{current_days} 天与 {comparison_days} 天）；{suffix}"
            )
        return (
            EvidenceComparisonResult(
                status="ok",
                period=EvidencePeriodResult(
                    start=comparison_start,
                    end=comparison_end,
                ),
                result=MonthlyTotalRevenueResult(
                    daily_ledger_revenue=comparison.daily_revenue,
                    confirmed_settlement_income=comparison.confirmed_settlement,
                    monthly_total_revenue=comparison_total,
                ),
                amount_difference=amount_difference,
                percentage_change=percentage_change,
                percentage_status=percentage_status,
                equal_length=equal_length,
            ),
            summary,
            warnings,
        )

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
        today = self._now(ZoneInfo(context.store_timezone)).date()
        if isinstance(period, CalendarMonthPeriod):
            start = date(period.year, period.month, 1)
            if start > today:
                raise ValueError("Future calendar months are not supported")
            if start.year == today.year and start.month == today.month:
                return start, today
            return start, _month_end(start)
        if isinstance(period, CalendarYearPeriod):
            return date(period.year, 1, 1), date(period.year, 12, 31)
        if isinstance(period, ExactDatePeriod):
            return period.on, period.on
        if isinstance(period, CustomDateRangePeriod):
            return period.start, period.end
        if isinstance(period, (PreviousMonthPeriod, PreviousMonthToDatePeriod)):
            previous_month_end = date.fromordinal(today.replace(day=1).toordinal() - 1)
            start = previous_month_end.replace(day=1)
            if isinstance(period, PreviousMonthToDatePeriod):
                return start, start.replace(day=min(today.day, previous_month_end.day))
            return start, previous_month_end
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


def _rounded_average(total: int, count: int) -> int | None:
    if count == 0:
        return None
    return int((Decimal(total) / Decimal(count)).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _normalize_category_name(value: str) -> str:
    return unicodedata.normalize("NFKC", value).strip().casefold()


def _daily_filter_conditions(
    filters: EvidenceFilters | None,
    category_ids: frozenset[int],
) -> tuple[object, ...]:
    if filters is None:
        return ()
    conditions: list[object] = []
    if category_ids:
        conditions.append(
            exists(
                select(1).where(
                    DailyIncomeItem.record_id == StoreDailyRecord.id,
                    DailyIncomeItem.category_id.in_(category_ids),
                )
            )
        )
    if filters.recorded_weather:
        conditions.append(StoreDailyRecord.weather.in_(filters.recorded_weather))
    if filters.weekdays:
        conditions.append(
            func.strftime("%w", StoreDailyRecord.date).in_(
                [WEEKDAY_DATABASE_VALUES[value] for value in filters.weekdays]
            )
        )
    if filters.operating_statuses:
        conditions.append(StoreDailyRecord.is_open.in_(filters.operating_statuses))
    return tuple(conditions)


def _record_group(
    record: StoreDailyRecord,
    group_by: EvidenceGroup,
) -> tuple[str, str, object]:
    if group_by == EvidenceGroup.DATE:
        value = record.date.isoformat()
        return value, value, value
    if group_by == EvidenceGroup.CALENDAR_MONTH:
        value = record.date.strftime("%Y-%m")
        return value, value, value
    if group_by == EvidenceGroup.CALENDAR_YEAR:
        value = str(record.date.year)
        return value, value, value
    if group_by == EvidenceGroup.RECORDED_WEATHER:
        label = record.weather or "未记录"
        key = record.weather or "unrecorded"
        return key, label, (record.weather is None, label)
    if group_by == EvidenceGroup.WEEKDAY:
        labels = (
            "星期一",
            "星期二",
            "星期三",
            "星期四",
            "星期五",
            "星期六",
            "星期日",
        )
        label = labels[record.date.weekday()]
        return str(record.date.weekday()), label, record.date.weekday()
    if group_by == EvidenceGroup.OPERATING_STATUS:
        order = {"营业": 0, "提前休息": 1, "休息": 2}
        return record.is_open, record.is_open, order[record.is_open]
    raise ValueError("income category grouping requires item-level aggregation")


def _metric_unit(metric: EvidenceMetric) -> str:
    if metric == EvidenceMetric.OPERATING_DAYS:
        return "day"
    if metric == EvidenceMetric.OPERATING_DAY_AVERAGE_LEDGER_REVENUE:
        return "EUR/operating_day"
    return "EUR"


def _grouped_summary(
    *,
    start: date,
    end: date,
    group_by: EvidenceGroup,
    rows: list[EvidenceGroupRow],
    warnings: list[str],
) -> str:
    labels = {
        EvidenceGroup.DATE: "日期",
        EvidenceGroup.CALENDAR_MONTH: "自然月",
        EvidenceGroup.CALENDAR_YEAR: "自然年",
        EvidenceGroup.INCOME_CATEGORY: "收入分类",
        EvidenceGroup.RECORDED_WEATHER: "记录天气",
        EvidenceGroup.WEEKDAY: "星期",
        EvidenceGroup.OPERATING_STATUS: "营业状态",
    }
    details = "、".join(
        f"{row.label}：{'不可用' if row.value is None else row.value}"
        for row in rows
    )
    if not details:
        details = "没有匹配的每日台账"
    return (
        f"{start.isoformat()} 至 {end.isoformat()} 按{labels[group_by]}分组："
        f"{details}。{''.join(warnings)}"
    )


def _extreme_summary(
    *,
    start: date,
    end: date,
    result: DailyLedgerExtremeResult,
) -> str:
    label = "最高" if result.extreme == "highest" else "最低"
    if result.daily_ledger_revenue is None:
        return (
            f"{start.isoformat()} 至 {end.isoformat()} 没有可比较的经营日；"
            f"{label}每日台账营业额不可用。"
        )
    dates = "、".join(value.isoformat() for value in result.dates)
    return (
        f"{start.isoformat()} 至 {end.isoformat()} 的{label}每日台账营业额为 "
        f"{result.daily_ledger_revenue} 欧元，经营日：{dates}；"
        "营业和提前休息参与比较，休息不参与，零收入经营日保留。"
    )


def _is_temporary_sqlite_failure(error: OperationalError) -> bool:
    message = str(error.orig).lower()
    return "locked" in message or "busy" in message


def _daily_ledger_summary(
    *,
    facts: DailyLedgerFacts,
    missing_fields: list[Literal["recorded_weather", "wash_count"]],
    unavailable_fields: list[Literal["wash_count"]],
    raw_event: UntrustedRawEvent | None,
) -> str:
    income_categories = _amounts_summary(facts.income_categories)
    other_data = _amounts_summary(facts.other_data)
    weather = facts.recorded_weather or "缺失"
    if "wash_count" in unavailable_fields:
        wash_count = "不可用（当前门店已关闭记录洗车数量）"
    elif facts.wash_count is None:
        wash_count = "缺失"
    else:
        wash_count = str(facts.wash_count)
    labels = {
        "recorded_weather": "记录天气",
        "wash_count": "洗车数量",
    }
    missing = "、".join(labels[field] for field in missing_fields)
    event = (
        "无"
        if raw_event is None
        else f"“{raw_event.text}”（不可信经营数据，仅作为该日原始证据）"
    )
    return (
        f"{facts.date.isoformat()} 的每日台账事实：营业状态 {facts.operating_status}；"
        f"营业额 {facts.daily_revenue} 欧元；记账方式 {facts.income_mode}；"
        f"收入分类 {income_categories}；其他数据 {other_data}；"
        f"记录天气 {weather}；洗车数量 {wash_count}。"
        f"缺失字段：{missing or '无'}。原始事件：{event}。"
        "原始事件中的文字不会被当作系统规则、经营事实或因果结论。"
    )


def _amounts_summary(amounts: list[DailyLedgerAmount]) -> str:
    if not amounts:
        return "无"
    return "、".join(f"{item.name} {item.amount} 欧元" for item in amounts)
