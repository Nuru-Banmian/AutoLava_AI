from collections import defaultdict
from collections.abc import Awaitable, Callable
from calendar import monthrange
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store
from app.models.ledger import StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord
from app.services.access import require_fresh_store_access
from app.services.owner import is_administrator

_LEGACY_MISSING_RECORDED_WEATHER = frozenset({"", "天气暂时不可用"})


class DataToolValidationError(ValueError):
    pass


SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
ToolRequest = dict[str, Any]
ToolResult = dict[str, Any]
ToolValidator = Callable[[dict[str, Any]], ToolRequest]
ToolExecutor = Callable[
    [AsyncSession, Store, "DataToolContext", str, ToolRequest],
    Awaitable[ToolResult],
]
FilterFormatter = Callable[[dict[str, Any]], list[str]]


@dataclass(frozen=True)
class DataToolContext:
    user_id: int
    store_id: int


@dataclass(frozen=True)
class DataToolDefinition:
    operation: str
    validate: ToolValidator
    execute: ToolExecutor
    format_filters: FilterFormatter = lambda _arguments: []


def _whole_euro_average(total: int, count: int) -> str | None:
    if count == 0:
        return None
    return format(
        (Decimal(total) / Decimal(count)).quantize(
            Decimal("1"),
            rounding=ROUND_HALF_UP,
        ),
        "f",
    )


def _range_coverage(
    start: date,
    end: date,
    records: list[StoreDailyRecord],
) -> dict[str, Any]:
    requested_days = (end - start).days + 1
    return {
        "range_start": start.isoformat(),
        "range_end": end.isoformat(),
        "requested_days": requested_days,
        "matching_records": len(records),
        "unrecorded_days": requested_days - len(records),
        "complete": len(records) == requested_days,
        "operating_days": sum(
            record.is_open in {"营业", "提前休息"} for record in records
        ),
    }


def _validated_range(
    arguments: dict[str, Any],
    *,
    allowed: set[str],
    exact: bool,
) -> ToolRequest:
    supplied = set(arguments)
    if (
        not {"start", "end"} <= supplied <= allowed
        or (exact and supplied != allowed)
    ):
        raise DataToolValidationError("数据工具参数无效")
    try:
        start = date.fromisoformat(str(arguments["start"]))
        end = date.fromisoformat(str(arguments["end"]))
    except ValueError as exc:
        raise DataToolValidationError("日期格式无效") from exc
    if start > end:
        raise DataToolValidationError("开始日期不能晚于结束日期")
    if (end - start).days > 366:
        raise DataToolValidationError("日期范围不能超过 367 天")
    return {"start": start, "end": end}


def _validate_summary(arguments: dict[str, Any]) -> ToolRequest:
    return _validated_range(
        arguments,
        allowed={"start", "end"},
        exact=True,
    )


def _validate_trend(arguments: dict[str, Any]) -> ToolRequest:
    request = _validated_range(
        arguments,
        allowed={"start", "end", "bucket"},
        exact=True,
    )
    bucket = arguments["bucket"]
    if bucket not in {"day", "month"}:
        raise DataToolValidationError("趋势粒度必须是 day 或 month")
    request["bucket"] = bucket
    return request


def _validate_context_group(arguments: dict[str, Any]) -> ToolRequest:
    request = _validated_range(
        arguments,
        allowed={"start", "end", "dimension"},
        exact=True,
    )
    dimension = arguments["dimension"]
    if dimension not in {"weekday", "recorded_weather"}:
        raise DataToolValidationError(
            "经营背景分组维度必须是 weekday 或 recorded_weather"
        )
    request["dimension"] = dimension
    return request


def _parse_month(value: object) -> date:
    text = str(value)
    if len(text) != 7:
        raise DataToolValidationError("开票月份格式无效")
    try:
        month = date.fromisoformat(f"{text}-01")
    except ValueError as exc:
        raise DataToolValidationError("开票月份格式无效") from exc
    if month.strftime("%Y-%m") != text:
        raise DataToolValidationError("开票月份格式无效")
    return month


def _month_end(month: date) -> date:
    return month.replace(day=monthrange(month.year, month.month)[1])


def _validated_month_range(
    arguments: dict[str, Any],
    *,
    allowed: set[str],
    required: set[str],
) -> ToolRequest:
    supplied = set(arguments)
    if not required <= supplied <= allowed:
        raise DataToolValidationError("数据工具参数无效")
    start_month = _parse_month(arguments["start_month"])
    end_month = _parse_month(arguments["end_month"])
    if start_month > end_month:
        raise DataToolValidationError("开始开票月份不能晚于结束开票月份")
    month_count = (
        (end_month.year - start_month.year) * 12
        + end_month.month
        - start_month.month
        + 1
    )
    if month_count > 24:
        raise DataToolValidationError("开票月份范围不能超过 24 个月")
    return {
        "start_month": start_month,
        "end_month": end_month,
        "start": start_month,
        "end": _month_end(end_month),
    }


def _validate_settlement_summary(arguments: dict[str, Any]) -> ToolRequest:
    request = _validated_month_range(
        arguments,
        allowed={"start_month", "end_month", "group_by"},
        required={"start_month", "end_month", "group_by"},
    )
    group_by = arguments["group_by"]
    if group_by not in {"opening_month", "company"}:
        raise DataToolValidationError(
            "公司结算汇总分组必须是 opening_month 或 company"
        )
    request["group_by"] = group_by
    return request


def _validate_settlement_detail(arguments: dict[str, Any]) -> ToolRequest:
    request = _validated_month_range(
        arguments,
        allowed={
            "start_month",
            "end_month",
            "company_id",
            "statuses",
            "limit",
            "offset",
        },
        required={"start_month", "end_month"},
    )
    company_id = arguments.get("company_id")
    if company_id is not None and (
        not isinstance(company_id, int)
        or isinstance(company_id, bool)
        or company_id <= 0
    ):
        raise DataToolValidationError("结算公司筛选无效")
    statuses = arguments.get("statuses")
    if statuses is not None and (
        not isinstance(statuses, list)
        or not statuses
        or len(statuses) > 2
        or len(set(statuses)) != len(statuses)
        or any(status not in {"pending", "confirmed"} for status in statuses)
    ):
        raise DataToolValidationError("公司结算当前状态筛选无效")
    limit, offset = _validated_page(arguments)
    request.update(
        {
            "company_id": company_id,
            "statuses": statuses,
            "limit": limit,
            "offset": offset,
        }
    )
    return request


def _validated_page(arguments: dict[str, Any]) -> tuple[int, int]:
    limit = arguments.get("limit", 20)
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 50
    ):
        raise DataToolValidationError("明细条数必须在 1 到 50 之间")
    offset = arguments.get("offset", 0)
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset <= 10000
    ):
        raise DataToolValidationError("明细偏移量无效")
    return limit, offset


def _validate_company_directory(arguments: dict[str, Any]) -> ToolRequest:
    if not set(arguments) <= {"statuses", "limit", "offset"}:
        raise DataToolValidationError("数据工具参数无效")
    statuses = arguments.get("statuses", ["active", "archived"])
    if (
        not isinstance(statuses, list)
        or not statuses
        or len(statuses) > 2
        or len(set(statuses)) != len(statuses)
        or any(status not in {"active", "archived"} for status in statuses)
    ):
        raise DataToolValidationError("结算公司目录状态筛选无效")
    limit, offset = _validated_page(arguments)
    return {
        "statuses": statuses,
        "limit": limit,
        "offset": offset,
    }


def _validate_detail(arguments: dict[str, Any]) -> ToolRequest:
    request = _validated_range(
        arguments,
        allowed={
            "start",
            "end",
            "operating_statuses",
            "recorded_weather",
            "events_only",
            "event_keyword",
            "missing_wash_count",
            "limit",
            "offset",
        },
        exact=False,
    )
    statuses = arguments.get("operating_statuses")
    if statuses is not None and (
        not isinstance(statuses, list)
        or not statuses
        or len(statuses) > 3
        or any(
            status not in {"营业", "休息", "提前休息"}
            for status in statuses
        )
    ):
        raise DataToolValidationError("营业状态筛选无效")
    weather = arguments.get("recorded_weather")
    if weather is not None and (
        not isinstance(weather, str) or not weather.strip()
    ):
        raise DataToolValidationError("记录天气筛选无效")
    events_only = arguments.get("events_only")
    if events_only is not None and not isinstance(events_only, bool):
        raise DataToolValidationError("事件筛选无效")
    event_keyword = arguments.get("event_keyword")
    if event_keyword is not None and (
        not isinstance(event_keyword, str)
        or not event_keyword.strip()
        or len(event_keyword) > 100
    ):
        raise DataToolValidationError("事件关键词无效")
    missing_wash_count = arguments.get("missing_wash_count")
    if missing_wash_count is not None and not isinstance(
        missing_wash_count,
        bool,
    ):
        raise DataToolValidationError("洗车数量缺失筛选无效")
    limit = arguments.get("limit", 20)
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or not 1 <= limit <= 50
    ):
        raise DataToolValidationError("明细条数必须在 1 到 50 之间")
    offset = arguments.get("offset", 0)
    if (
        not isinstance(offset, int)
        or isinstance(offset, bool)
        or not 0 <= offset <= 10000
    ):
        raise DataToolValidationError("明细偏移量无效")
    request.update(
        {
            "operating_statuses": statuses,
            "recorded_weather": weather,
            "events_only": events_only,
            "event_keyword": event_keyword,
            "missing_wash_count": missing_wash_count,
            "limit": limit,
            "offset": offset,
        }
    )
    return request


def _detail_filters(arguments: dict[str, Any]) -> list[str]:
    filters: list[str] = []
    statuses = arguments.get("operating_statuses")
    if statuses:
        filters.append(f"营业状态：{'、'.join(statuses)}")
    if arguments.get("recorded_weather"):
        filters.append(f"记录天气：{arguments['recorded_weather']}")
    if arguments.get("events_only") is True:
        filters.append("仅有事件")
    if arguments.get("event_keyword"):
        filters.append("已应用事件关键词筛选")
    if "missing_wash_count" in arguments:
        filters.append(
            "洗车数量：缺失"
            if arguments["missing_wash_count"]
            else "洗车数量：已记录"
        )
    return filters


def _context_group_filters(arguments: dict[str, Any]) -> list[str]:
    return [
        "分组维度：星期"
        if arguments["dimension"] == "weekday"
        else "分组维度：记录天气"
    ]


def _settlement_summary_filters(arguments: dict[str, Any]) -> list[str]:
    return [
        (
            "分组：开票月份"
            if arguments["group_by"] == "opening_month"
            else "分组：结算公司"
        )
    ]


def _settlement_detail_filters(arguments: dict[str, Any]) -> list[str]:
    filters: list[str] = []
    if arguments.get("company_id") is not None:
        filters.append("已筛选结算公司")
    if arguments.get("statuses"):
        labels = {
            "pending": "待到账",
            "confirmed": "已确认",
        }
        filters.append(
            f"当前状态：{'、'.join(labels[item] for item in arguments['statuses'])}"
        )
    return filters


def _company_directory_filters(arguments: dict[str, Any]) -> list[str]:
    labels = {"active": "使用中", "archived": "已归档"}
    statuses = arguments.get("statuses", ["active", "archived"])
    return [
        f"公司状态：{'、'.join(labels[item] for item in statuses)}"
    ]


class AgentDataToolRegistry:
    def __init__(self, session_factory: SessionFactory) -> None:
        self._session_factory = session_factory
        self._definitions = {
            "business_performance_summary": DataToolDefinition(
                operation="汇总经营表现",
                validate=_validate_summary,
                execute=self._execute_summary,
            ),
            "ledger_revenue_trend": DataToolDefinition(
                operation="查看台账营业额趋势",
                validate=_validate_trend,
                execute=self._execute_trend,
            ),
            "income_composition": DataToolDefinition(
                operation="查看分类数据构成",
                validate=_validate_summary,
                execute=self._execute_composition,
            ),
            "daily_ledger_detail": DataToolDefinition(
                operation="查看每日台账明细",
                validate=_validate_detail,
                execute=self._execute_detail,
                format_filters=_detail_filters,
            ),
            "business_context_group": DataToolDefinition(
                operation="按经营背景分组",
                validate=_validate_context_group,
                execute=self._execute_context_group,
                format_filters=_context_group_filters,
            ),
            "company_settlement_summary": DataToolDefinition(
                operation="汇总公司结算与应收",
                validate=_validate_settlement_summary,
                execute=self._execute_settlement_summary,
                format_filters=_settlement_summary_filters,
            ),
            "company_settlement_detail": DataToolDefinition(
                operation="查看公司结算明细",
                validate=_validate_settlement_detail,
                execute=self._execute_settlement_detail,
                format_filters=_settlement_detail_filters,
            ),
            "settlement_company_directory": DataToolDefinition(
                operation="查看结算公司目录",
                validate=_validate_company_directory,
                execute=self._execute_company_directory,
                format_filters=_company_directory_filters,
            ),
        }
        self.names = frozenset(self._definitions)

    async def execute(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: DataToolContext,
        result_id: str,
    ) -> ToolResult:
        try:
            definition = self._definitions[name]
        except KeyError as exc:
            raise DataToolValidationError("未知的数据工具") from exc
        request = definition.validate(arguments)
        async with self._session_factory() as session:
            user, store = await require_fresh_store_access(
                session,
                user_id=context.user_id,
                store_id=context.store_id,
                capability="analytics.view",
            )
            if not is_administrator(user):
                raise DataToolValidationError("数据分析 Agent 仅限管理员")
            try:
                local_today = datetime.now(ZoneInfo(store.timezone)).date()
            except (KeyError, ValueError):
                local_today = date.today()
            request["local_today"] = local_today
            if "end_month" in request and request["end_month"] > local_today.replace(
                day=1
            ):
                raise DataToolValidationError("结束开票月份不能晚于门店本地月份")
            if "end_month" not in request and request.get("end", local_today) > local_today:
                raise DataToolValidationError("结束日期不能晚于门店本地日期")
            return await definition.execute(
                session,
                store,
                context,
                result_id,
                request,
            )

    def investigation_card(
        self,
        name: str,
        arguments: dict[str, Any],
        result: ToolResult,
    ) -> dict[str, Any]:
        definition = self._definitions[name]
        coverage = result["coverage"]
        return {
            "operation": definition.operation,
            "range_start": coverage.get("range_start"),
            "range_end": coverage.get("range_end"),
            "filters": definition.format_filters(arguments),
            "status": "empty" if result["status"] == "empty" else "completed",
        }

    @staticmethod
    async def _records(
        session: AsyncSession,
        context: DataToolContext,
        request: ToolRequest,
    ) -> list[StoreDailyRecord]:
        return list(
            await session.scalars(
                select(StoreDailyRecord)
                .where(
                    StoreDailyRecord.store_id == context.store_id,
                    StoreDailyRecord.date.between(
                        request["start"],
                        request["end"],
                    ),
                )
                .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
            )
        )

    async def _execute_summary(
        self,
        session: AsyncSession,
        store: Store,
        context: DataToolContext,
        result_id: str,
        request: ToolRequest,
    ) -> ToolResult:
        records = await self._records(session, context, request)
        operating = [
            record
            for record in records
            if record.is_open in {"营业", "提前休息"}
        ]
        wash_records = (
            [
                record
                for record in operating
                if record.wash_count is not None
            ]
            if store.wash_count_enabled
            else []
        )
        wash_count = (
            sum(record.wash_count or 0 for record in wash_records)
            if wash_records
            else None
        )
        wash_revenue = sum(record.daily_revenue for record in wash_records)
        return {
            "result_id": result_id,
            "status": "success" if records else "empty",
            "data": {
                "ledger_revenue": str(
                    sum(record.daily_revenue for record in records)
                ),
                "operating_days": len(operating),
                "operating_day_average_ledger_revenue": (
                    _whole_euro_average(
                        sum(record.daily_revenue for record in operating),
                        len(operating),
                    )
                ),
                "wash_count": (
                    str(wash_count) if wash_count is not None else None
                ),
                "average_revenue_per_wash": (
                    _whole_euro_average(wash_revenue, wash_count)
                    if wash_count is not None and wash_count > 0
                    else None
                ),
            },
            "coverage": {
                **_range_coverage(
                    request["start"],
                    request["end"],
                    records,
                ),
                "business_basis": {
                    "income_modes": sorted(
                        {record.income_mode for record in records}
                    ),
                    "wash_count_enabled": store.wash_count_enabled,
                    "company_settlement_included": False,
                },
                "missing_wash_count_days": (
                    len(operating) - len(wash_records)
                ),
                "truncated": False,
            },
        }

    async def _execute_trend(
        self,
        session: AsyncSession,
        _store: Store,
        context: DataToolContext,
        result_id: str,
        request: ToolRequest,
    ) -> ToolResult:
        records = await self._records(session, context, request)
        totals: dict[str, int] = defaultdict(int)
        for record in records:
            period = (
                record.date.isoformat()
                if request["bucket"] == "day"
                else record.date.strftime("%Y-%m")
            )
            totals[period] += record.daily_revenue
        return {
            "result_id": result_id,
            "status": "success" if records else "empty",
            "data": {
                "bucket": request["bucket"],
                "points": [
                    {
                        "period": period,
                        "ledger_revenue": str(amount),
                    }
                    for period, amount in sorted(totals.items())
                ],
            },
            "coverage": {
                **_range_coverage(
                    request["start"],
                    request["end"],
                    records,
                ),
                "truncated": False,
            },
        }

    async def _execute_composition(
        self,
        session: AsyncSession,
        _store: Store,
        context: DataToolContext,
        result_id: str,
        request: ToolRequest,
    ) -> ToolResult:
        records = await self._records(session, context, request)
        grouped: dict[tuple[int, str, bool], dict[str, Any]] = {}
        for record in records:
            for item in record.items:
                key = (
                    item.category_id,
                    item.category_name,
                    item.include_in_total,
                )
                row = grouped.setdefault(
                    key,
                    {
                        "category_id": item.category_id,
                        "category_name": item.category_name,
                        "include_in_ledger_revenue": item.include_in_total,
                        "amount": 0,
                        "sort_order": item.sort_order,
                        "first_date": record.date,
                    },
                )
                row["amount"] += item.amount
                row["sort_order"] = min(row["sort_order"], item.sort_order)
                row["first_date"] = min(row["first_date"], record.date)
        included = sorted(
            (
                row
                for row in grouped.values()
                if row["include_in_ledger_revenue"]
            ),
            key=lambda row: (
                row["sort_order"],
                row["category_id"],
                row["first_date"],
            ),
        )
        excluded = sorted(
            (
                row
                for row in grouped.values()
                if not row["include_in_ledger_revenue"]
            ),
            key=lambda row: (
                row["sort_order"],
                row["category_id"],
                row["first_date"],
            ),
        )
        included_total = sum(row["amount"] for row in included)
        excluded_total = sum(row["amount"] for row in excluded)
        income_categories = [
            {
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "include_in_ledger_revenue": True,
                "amount": str(row["amount"]),
                "proportion": (
                    format(
                        (
                            Decimal(row["amount"])
                            * Decimal(100)
                            / Decimal(included_total)
                        ).quantize(
                            Decimal("0.1"),
                            rounding=ROUND_HALF_UP,
                        ),
                        "f",
                    )
                    if included_total > 0
                    else None
                ),
            }
            for row in included
        ]
        other_data = [
            {
                "category_id": row["category_id"],
                "category_name": row["category_name"],
                "include_in_ledger_revenue": False,
                "amount": str(row["amount"]),
            }
            for row in excluded
        ]
        return {
            "result_id": result_id,
            "status": "success" if grouped else "empty",
            "data": {
                "classified_ledger_revenue": str(included_total),
                "income_categories": income_categories,
                "other_data_total": str(excluded_total),
                "other_data": other_data,
            },
            "coverage": {
                **_range_coverage(
                    request["start"],
                    request["end"],
                    records,
                ),
                "classified_records": sum(
                    bool(record.items) for record in records
                ),
                "truncated": False,
            },
        }

    async def _execute_detail(
        self,
        session: AsyncSession,
        _store: Store,
        context: DataToolContext,
        result_id: str,
        request: ToolRequest,
    ) -> ToolResult:
        filters = [
            StoreDailyRecord.store_id == context.store_id,
            StoreDailyRecord.date.between(
                request["start"],
                request["end"],
            ),
        ]
        if request["operating_statuses"] is not None:
            filters.append(
                StoreDailyRecord.is_open.in_(
                    request["operating_statuses"]
                )
            )
        if request["recorded_weather"] is not None:
            filters.append(
                StoreDailyRecord.weather == request["recorded_weather"]
            )
        if request["events_only"]:
            filters.extend(
                (
                    StoreDailyRecord.activity.is_not(None),
                    StoreDailyRecord.activity != "",
                )
            )
        if request["event_keyword"] is not None:
            filters.append(
                StoreDailyRecord.activity.contains(request["event_keyword"])
            )
        if request["missing_wash_count"] is not None:
            filters.append(
                StoreDailyRecord.wash_count.is_(None)
                if request["missing_wash_count"]
                else StoreDailyRecord.wash_count.is_not(None)
            )
        matching_records = int(
            await session.scalar(
                select(func.count(StoreDailyRecord.id)).where(*filters)
            )
            or 0
        )
        missing_wash_count_days = int(
            await session.scalar(
                select(func.count(StoreDailyRecord.id)).where(
                    *filters,
                    StoreDailyRecord.wash_count.is_(None),
                )
            )
            or 0
        )
        records = list(
            await session.scalars(
                select(StoreDailyRecord)
                .where(*filters)
                .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
                .offset(request["offset"])
                .limit(request["limit"])
            )
        )
        next_offset = (
            request["offset"] + len(records)
            if request["offset"] + len(records) < matching_records
            else None
        )
        return {
            "result_id": result_id,
            "status": "success" if records else "empty",
            "data": {
                "records": [
                    {
                        "date": record.date.isoformat(),
                        "ledger_revenue": str(record.daily_revenue),
                        "operating_status": record.is_open,
                        "wash_count": (
                            str(record.wash_count)
                            if record.wash_count is not None
                            else None
                        ),
                        "recorded_weather": record.weather,
                        "event": record.activity,
                    }
                    for record in records
                ]
            },
            "coverage": {
                "range_start": request["start"].isoformat(),
                "range_end": request["end"].isoformat(),
                "matching_records": matching_records,
                "returned_records": len(records),
                "missing_wash_count_days": missing_wash_count_days,
                "truncated": next_offset is not None,
                "next_offset": next_offset,
            },
        }

    async def _execute_context_group(
        self,
        session: AsyncSession,
        _store: Store,
        context: DataToolContext,
        result_id: str,
        request: ToolRequest,
    ) -> ToolResult:
        records = await self._records(session, context, request)
        operating = [
            record
            for record in records
            if record.is_open in {"营业", "提前休息"}
        ]
        grouped: dict[str, list[StoreDailyRecord]] = defaultdict(list)
        missing_dimension_days = 0
        for record in operating:
            if request["dimension"] == "weekday":
                key = str(record.date.isoweekday())
            else:
                key = record.weather
                if (
                    key is None
                    or key.strip() in _LEGACY_MISSING_RECORDED_WEATHER
                ):
                    missing_dimension_days += 1
                    continue
            grouped[key].append(record)

        weekday_labels = {
            "1": "星期一",
            "2": "星期二",
            "3": "星期三",
            "4": "星期四",
            "5": "星期五",
            "6": "星期六",
            "7": "星期日",
        }
        groups = []
        for key in sorted(
            grouped,
            key=int if request["dimension"] == "weekday" else str,
        ):
            group_records = grouped[key]
            revenue = sum(record.daily_revenue for record in group_records)
            groups.append(
                {
                    "key": key,
                    "label": (
                        weekday_labels[key]
                        if request["dimension"] == "weekday"
                        else key
                    ),
                    "operating_days": len(group_records),
                    "ledger_revenue": str(revenue),
                    "operating_day_average_ledger_revenue": (
                        _whole_euro_average(revenue, len(group_records))
                    ),
                }
            )

        return {
            "result_id": result_id,
            "status": "success" if groups else "empty",
            "data": {
                "dimension": request["dimension"],
                "groups": groups,
            },
            "coverage": {
                **_range_coverage(
                    request["start"],
                    request["end"],
                    records,
                ),
                "missing_dimension_days": missing_dimension_days,
                "truncated": False,
            },
        }

    @staticmethod
    async def _settlement_records(
        session: AsyncSession,
        context: DataToolContext,
        request: ToolRequest,
    ) -> list[SettlementRecord]:
        return list(
            await session.scalars(
                select(SettlementRecord)
                .where(
                    SettlementRecord.store_id == context.store_id,
                    SettlementRecord.opening_month.between(
                        request["start_month"],
                        request["end_month"],
                    ),
                )
                .order_by(
                    SettlementRecord.opening_month,
                    func.lower(SettlementRecord.company_name),
                    SettlementRecord.created_at,
                    SettlementRecord.id,
                )
            )
        )

    async def _execute_settlement_summary(
        self,
        session: AsyncSession,
        store: Store,
        context: DataToolContext,
        result_id: str,
        request: ToolRequest,
    ) -> ToolResult:
        records = await self._settlement_records(session, context, request)
        confirmed = sum(
            record.amount for record in records if record.status == "confirmed"
        )
        pending = sum(
            record.amount for record in records if record.status == "pending"
        )
        grouped: dict[object, dict[str, Any]] = {}
        company_names = {
            company.id: company.name
            for company in await session.scalars(
                select(SettlementCompany).where(
                    SettlementCompany.store_id == context.store_id
                )
            )
        }
        for record in records:
            if request["group_by"] == "opening_month":
                key: object = record.opening_month
                row = grouped.setdefault(
                    key,
                    {
                        "opening_month": record.opening_month.strftime("%Y-%m"),
                        "confirmed_settlement_income": 0,
                        "current_pending_receivables": 0,
                    },
                )
            else:
                key = record.company_id
                row = grouped.setdefault(
                    key,
                    {
                        "company_id": record.company_id,
                        "company_name": company_names.get(
                            record.company_id,
                            record.company_name,
                        ),
                        "confirmed_settlement_income": 0,
                        "current_pending_receivables": 0,
                    },
                )
            field = (
                "confirmed_settlement_income"
                if record.status == "confirmed"
                else "current_pending_receivables"
            )
            row[field] += record.amount

        ordered_rows = sorted(
            grouped.values(),
            key=(
                (lambda row: row["opening_month"])
                if request["group_by"] == "opening_month"
                else (
                    lambda row: (
                        row["company_name"].casefold(),
                        row["company_id"],
                    )
                )
            ),
        )
        groups = []
        for row in ordered_rows:
            groups.append(
                {
                    **row,
                    "confirmed_settlement_income": str(
                        row["confirmed_settlement_income"]
                    ),
                    "current_pending_receivables": str(
                        row["current_pending_receivables"]
                    ),
                }
            )
        return {
            "result_id": result_id,
            "status": "success" if records else "empty",
            "data": {
                "group_by": request["group_by"],
                "confirmed_settlement_income": str(confirmed),
                "current_pending_receivables": str(pending),
                "groups": groups,
            },
            "coverage": {
                "range_start": request["start"].isoformat(),
                "range_end": request["end"].isoformat(),
                "matching_records": len(records),
                "state_basis": "current",
                "snapshot_date": request["local_today"].isoformat(),
                "company_settlement_enabled": store.company_settlement_enabled,
                "truncated": False,
            },
        }

    async def _execute_settlement_detail(
        self,
        session: AsyncSession,
        _store: Store,
        context: DataToolContext,
        result_id: str,
        request: ToolRequest,
    ) -> ToolResult:
        filters = [
            SettlementRecord.store_id == context.store_id,
            SettlementRecord.opening_month.between(
                request["start_month"],
                request["end_month"],
            ),
        ]
        if request["company_id"] is not None:
            filters.append(
                SettlementRecord.company_id == request["company_id"]
            )
        if request["statuses"] is not None:
            filters.append(SettlementRecord.status.in_(request["statuses"]))
        matching_records = int(
            await session.scalar(
                select(func.count(SettlementRecord.id)).where(*filters)
            )
            or 0
        )
        records = list(
            await session.scalars(
                select(SettlementRecord)
                .where(*filters)
                .order_by(
                    SettlementRecord.opening_month,
                    func.lower(SettlementRecord.company_name),
                    SettlementRecord.created_at,
                    SettlementRecord.id,
                )
                .offset(request["offset"])
                .limit(request["limit"])
            )
        )
        next_offset = (
            request["offset"] + len(records)
            if request["offset"] + len(records) < matching_records
            else None
        )
        return {
            "result_id": result_id,
            "status": "success" if records else "empty",
            "data": {
                "records": [
                    {
                        "record_id": record.id,
                        "opening_month": record.opening_month.strftime("%Y-%m"),
                        "company_id": record.company_id,
                        "company_name": record.company_name,
                        "amount": str(record.amount),
                        "status": record.status,
                    }
                    for record in records
                ]
            },
            "coverage": {
                "range_start": request["start"].isoformat(),
                "range_end": request["end"].isoformat(),
                "matching_records": matching_records,
                "returned_records": len(records),
                "truncated": next_offset is not None,
                "next_offset": next_offset,
                "state_basis": "current",
            },
        }

    async def _execute_company_directory(
        self,
        session: AsyncSession,
        store: Store,
        context: DataToolContext,
        result_id: str,
        request: ToolRequest,
    ) -> ToolResult:
        active_values = [
            status == "active" for status in request["statuses"]
        ]
        filters = [
            SettlementCompany.store_id == context.store_id,
            SettlementCompany.is_active.in_(active_values),
        ]
        matching_companies = int(
            await session.scalar(
                select(func.count(SettlementCompany.id)).where(*filters)
            )
            or 0
        )
        companies = list(
            await session.scalars(
                select(SettlementCompany)
                .where(*filters)
                .order_by(
                    SettlementCompany.is_active.desc(),
                    SettlementCompany.normalized_name,
                    SettlementCompany.id,
                )
                .offset(request["offset"])
                .limit(request["limit"])
            )
        )
        next_offset = (
            request["offset"] + len(companies)
            if request["offset"] + len(companies) < matching_companies
            else None
        )
        return {
            "result_id": result_id,
            "status": "success" if companies else "empty",
            "data": {
                "companies": [
                    {
                        "company_id": company.id,
                        "company_name": company.name,
                        "status": (
                            "active" if company.is_active else "archived"
                        ),
                    }
                    for company in companies
                ]
            },
            "coverage": {
                "range_start": None,
                "range_end": None,
                "matching_companies": matching_companies,
                "returned_companies": len(companies),
                "includes_companies_without_records": True,
                "company_settlement_enabled": store.company_settlement_enabled,
                "truncated": next_offset is not None,
                "next_offset": next_offset,
            },
        }
