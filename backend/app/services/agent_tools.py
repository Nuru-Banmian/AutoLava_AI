import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, cast, get_args
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, IncomeCategory, StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord
from app.services.access import require_fresh_store_access
from app.services.income_config import IncomeConfigService

JsonObject = dict[str, Any]
SettlementGroup = Literal["company", "opening_month", "status"]
DailyFilter = Literal[
    "operating_status",
    "weekdays",
    "recorded_weather",
    "has_event",
    "wash_count_covered",
]
DAILY_FILTERS = cast(tuple[DailyFilter, ...], get_args(DailyFilter))
OPERATING_STATUSES = ("营业", "休息", "提前休息")
OPERATING_DAY_STATUSES = {"营业", "提前休息"}
WEEKDAYS = (
    "星期一",
    "星期二",
    "星期三",
    "星期四",
    "星期五",
    "星期六",
    "星期日",
)


@dataclass(frozen=True)
class DailyDimension:
    filter_name: DailyFilter
    group_name: str
    record_key: str
    schema: JsonObject
    allowed_values: set[object] | None = None
    sort_order: tuple[object, ...] | None = None


DAILY_DIMENSIONS = (
    DailyDimension(
        filter_name="operating_status",
        group_name="operating_status",
        record_key="operating_status",
        schema={
            "type": "array",
            "items": {"type": "string", "enum": list(OPERATING_STATUSES)},
            "uniqueItems": True,
        },
        allowed_values=set(OPERATING_STATUSES),
        sort_order=OPERATING_STATUSES,
    ),
    DailyDimension(
        filter_name="weekdays",
        group_name="weekday",
        record_key="weekday",
        schema={
            "type": "array",
            "items": {"type": "string", "enum": list(WEEKDAYS)},
            "uniqueItems": True,
        },
        allowed_values=set(WEEKDAYS),
        sort_order=WEEKDAYS,
    ),
    DailyDimension(
        filter_name="recorded_weather",
        group_name="recorded_weather",
        record_key="recorded_weather",
        schema={
            "type": "array",
            "items": {"type": ["string", "null"]},
            "uniqueItems": True,
        },
    ),
    DailyDimension(
        filter_name="has_event",
        group_name="has_event",
        record_key="has_event",
        schema={"type": "boolean"},
    ),
    DailyDimension(
        filter_name="wash_count_covered",
        group_name="wash_count_coverage",
        record_key="wash_count_covered",
        schema={"type": "boolean"},
    ),
)
DAILY_DIMENSIONS_BY_FILTER = {
    dimension.filter_name: dimension for dimension in DAILY_DIMENSIONS
}
DAILY_DIMENSIONS_BY_GROUP = {
    dimension.group_name: dimension for dimension in DAILY_DIMENSIONS
}
DailyGroup = Literal[
    "operating_status",
    "weekday",
    "recorded_weather",
    "has_event",
    "wash_count_coverage",
]


@dataclass(frozen=True)
class AgentToolContext:
    session: AsyncSession
    user_id: int
    store_id: int
    now: datetime


@dataclass(frozen=True)
class AuthorizedToolContext:
    session: AsyncSession
    user_id: int
    store: Store
    local_today: date


@dataclass(frozen=True)
class HistoricalCategorySnapshot:
    category_id: int
    category_name: str
    include_in_total: bool


ToolHandler = Callable[[AuthorizedToolContext, Mapping[str, Any]], Awaitable[JsonObject]]


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    parameters: JsonObject
    handler: ToolHandler

    def schema(self) -> JsonObject:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


class AgentToolRegistry:
    def __init__(self, tools: Sequence[AgentTool] = ()) -> None:
        self._tools = {tool.name: tool for tool in tools}

    @property
    def schemas(self) -> list[JsonObject]:
        return [tool.schema() for tool in self._tools.values()]

    async def execute(
        self, tool_call: Mapping[str, Any], context: AgentToolContext
    ) -> JsonObject:
        call_id = str(tool_call.get("id", ""))
        function = tool_call.get("function")
        if not isinstance(function, Mapping):
            return _tool_error(call_id, "工具调用格式无效")
        name = function.get("name")
        tool = self._tools.get(name) if isinstance(name, str) else None
        if tool is None:
            return _tool_error(call_id, "工具不存在或未获授权")
        try:
            arguments = json.loads(str(function.get("arguments", "{}")))
        except json.JSONDecodeError:
            return _tool_error(call_id, "工具参数不是有效 JSON")
        if not isinstance(arguments, dict) or not _arguments_match(
            arguments, tool.parameters
        ):
            return _tool_error(call_id, "工具参数不符合定义")

        user, store = await require_fresh_store_access(
            context.session,
            user_id=context.user_id,
            store_id=context.store_id,
            capability="ledger.view",
        )
        result = await tool.handler(
            AuthorizedToolContext(
                session=context.session,
                user_id=user.id,
                store=store,
                local_today=context.now.astimezone(ZoneInfo(store.timezone)).date(),
            ),
            arguments,
        )
        return {
            "role": "tool",
            "tool_call_id": call_id,
            "name": tool.name,
            "content": json.dumps(result, ensure_ascii=False, separators=(",", ":")),
        }


def _tool_error(call_id: str, message: str) -> JsonObject:
    return {
        "role": "tool",
        "tool_call_id": call_id,
        "content": json.dumps({"error": message}, ensure_ascii=False),
    }


def _arguments_match(arguments: Mapping[str, Any], schema: Mapping[str, Any]) -> bool:
    properties = schema.get("properties", {})
    if not isinstance(properties, Mapping):
        return False
    if schema.get("additionalProperties") is False and not set(arguments).issubset(
        properties
    ):
        return False
    required = schema.get("required", [])
    return isinstance(required, list) and set(required).issubset(arguments)


def _coverage(row: Sequence[Any]) -> JsonObject:
    count, start_date, end_date = row
    return {
        "record_count": int(count or 0),
        "start_date": _date_value(start_date),
        "end_date": _date_value(end_date),
    }


def _date_value(value: date | None) -> str | None:
    return value.isoformat() if value is not None else None


async def _query_coverage(
    session: AsyncSession,
    id_column: InstrumentedAttribute[int],
    date_column: InstrumentedAttribute[date],
    *conditions: ColumnElement[bool],
) -> JsonObject:
    row = (
        await session.execute(
            select(
                func.count(id_column),
                func.min(date_column),
                func.max(date_column),
            ).where(*conditions)
        )
    ).one()
    return _coverage(row)


async def get_store_data_catalog(
    context: AuthorizedToolContext, _: Mapping[str, Any]
) -> JsonObject:
    session = context.session
    store = context.store
    categories = list(
        await session.scalars(
            select(IncomeCategory)
            .where(
                IncomeCategory.store_id == store.id,
                IncomeCategory.archived_at.is_(None),
            )
            .order_by(IncomeCategory.sort_order, IncomeCategory.id)
        )
    )
    daily_coverage = await _query_coverage(
        session,
        StoreDailyRecord.id,
        StoreDailyRecord.date,
        StoreDailyRecord.store_id == store.id,
    )
    wash_coverage = await _query_coverage(
        session,
        StoreDailyRecord.id,
        StoreDailyRecord.date,
        StoreDailyRecord.store_id == store.id,
        StoreDailyRecord.wash_count.is_not(None),
    )
    weather_coverage = await _query_coverage(
        session,
        StoreDailyRecord.id,
        StoreDailyRecord.date,
        StoreDailyRecord.store_id == store.id,
        StoreDailyRecord.weather.is_not(None),
    )
    event_coverage = await _query_coverage(
        session,
        StoreDailyRecord.id,
        StoreDailyRecord.date,
        StoreDailyRecord.store_id == store.id,
        StoreDailyRecord.activity.is_not(None),
    )
    settlement_coverage = await _query_coverage(
        session,
        SettlementRecord.id,
        SettlementRecord.opening_month,
        SettlementRecord.store_id == store.id,
    )
    config = IncomeConfigService.response(store, categories)
    return {
        "store": {"name": store.name, "timezone": store.timezone},
        "bookkeeping": {
            "mode": "categorized" if store.income_items_enabled else "total",
            "wash_count_enabled": store.wash_count_enabled,
            "company_settlement_enabled": store.company_settlement_enabled,
            "revenue_formula": config.formula,
        },
        "income_categories": [
            {
                "id": category.id,
                "name": category.name,
                "include_in_total": category.include_in_total,
                "is_active": category.is_active,
            }
            for category in categories
        ],
        "available_business_fields": [
            {"name": "daily_revenue", "available": True},
            {"name": "operating_status", "available": True},
            {"name": "income_categories", "available": store.income_items_enabled},
            {"name": "wash_count", "available": store.wash_count_enabled},
            {"name": "recorded_weather", "available": True},
            {"name": "event", "available": True},
            {
                "name": "company_settlement",
                "available": store.company_settlement_enabled,
            },
        ],
        "data_coverage": {
            "daily_records": daily_coverage,
            "wash_count": wash_coverage,
            "recorded_weather": weather_coverage,
            "events": event_coverage,
            "company_settlement": settlement_coverage,
        },
    }


_EXPLICIT_RANGE = re.compile(
    r"^\s*(?P<start>\d{4}(?:-|年)\d{1,2}(?:-|月)\d{1,2}日?)"
    r"\s*(?:至|到|~|—|–)\s*"
    r"(?P<end>(?:\d{4}(?:-|年)\d{1,2}(?:-|月))?\d{1,2}日?)\s*$"
)
_RECENT_WEEKS = re.compile(r"^最近\s*(?P<count>\d+|[一二三四五六七八九十]+)\s*周$")
_CHINESE_DIGITS = {
    "一": 1,
    "二": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
    "十": 10,
}


def _month_start(value: date) -> date:
    return value.replace(day=1)


def _previous_month(value: date) -> tuple[date, date]:
    end = _month_start(value) - timedelta(days=1)
    return _month_start(end), end


def _parse_date(
    value: str, *, default_year: int | None = None, default_month: int | None = None
) -> date:
    normalized = value.replace("年", "-").replace("月", "-").removesuffix("日")
    parts = normalized.split("-")
    if len(parts) == 1 and default_year is not None and default_month is not None:
        year, month, day = str(default_year), str(default_month), parts[0]
    else:
        year, month, day = parts
    return date(int(year), int(month), int(day))


def _chinese_number(value: str) -> int:
    if value.isdigit():
        return int(value)
    if value in _CHINESE_DIGITS:
        return _CHINESE_DIGITS[value]
    if value.startswith("十"):
        return 10 + _CHINESE_DIGITS.get(value[1:], 0)
    if "十" in value:
        tens, ones = value.split("十", 1)
        return _CHINESE_DIGITS[tens] * 10 + _CHINESE_DIGITS.get(ones, 0)
    raise ValueError


def _resolve_period(value: object, *, local_today: date) -> tuple[date, date] | str:
    if not isinstance(value, str) or not value.strip():
        return "期间必须是非空文本"
    period = value.strip()
    if period == "上个月":
        return _previous_month(local_today)
    if period == "今年":
        return date(local_today.year, 1, 1), local_today
    recent_weeks = _RECENT_WEEKS.fullmatch(period)
    if recent_weeks is not None:
        try:
            count = _chinese_number(recent_weeks["count"])
        except (KeyError, ValueError):
            return "无法识别最近周数"
        if not 1 <= count <= 52:
            return "最近周数必须在 1 至 52 之间"
        return local_today - timedelta(days=count * 7 - 1), local_today
    explicit = _EXPLICIT_RANGE.fullmatch(period)
    if explicit is None:
        return "无法识别期间，请使用上个月、今年、最近若干周或明确起止日期"
    try:
        start = _parse_date(explicit["start"])
        end = _parse_date(
            explicit["end"], default_year=start.year, default_month=start.month
        )
    except ValueError:
        return "期间包含无效自然日"
    if start > end:
        return "期间起始日期不能晚于结束日期"
    if end > local_today:
        return "期间结束日期不能晚于门店当地今天"
    return start, end


def _settlement_breakdown(
    records: Sequence[SettlementRecord],
    *,
    group_by: SettlementGroup,
    first_month: date,
    last_month: date,
    company_names: Mapping[int, str],
) -> list[JsonObject]:
    grouped: dict[object, JsonObject] = {}
    for record in records:
        in_period = first_month <= record.opening_month <= last_month
        if record.status == "confirmed" and not in_period:
            continue
        if group_by == "company":
            key: object = record.company_id
            identity = {
                "company_id": record.company_id,
                "company_name": company_names.get(
                    record.company_id, record.company_name
                ),
            }
        elif group_by == "opening_month":
            key = record.opening_month.strftime("%Y-%m")
            identity = {"opening_month": key}
        else:
            key = record.status
            identity = {"status": record.status}
        row = grouped.setdefault(
            key,
            {
                **identity,
                "confirmed_settlement_income": 0,
                "current_pending_receivables": 0,
            },
        )
        field = (
            "confirmed_settlement_income"
            if record.status == "confirmed"
            else "current_pending_receivables"
        )
        row[field] = int(row[field]) + record.amount
    return [grouped[key] for key in sorted(grouped)]


async def get_period_revenue(
    context: AuthorizedToolContext, arguments: Mapping[str, Any]
) -> JsonObject:
    resolved = _resolve_period(arguments.get("period"), local_today=context.local_today)
    if isinstance(resolved, str):
        return {"status": "error", "error": resolved}
    start, end = resolved
    raw_group_by = arguments.get("settlement_group_by", "company")
    if raw_group_by not in {"company", "opening_month", "status"}:
        return {"status": "error", "error": "公司结算分组方式无效"}
    group_by = cast(SettlementGroup, raw_group_by)

    daily_rows = (
        await context.session.execute(
            select(StoreDailyRecord.date, StoreDailyRecord.daily_revenue)
            .where(
                StoreDailyRecord.store_id == context.store.id,
                StoreDailyRecord.date.between(start, end),
            )
            .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
        )
    ).tuples()
    first_month = _month_start(start)
    last_month = _month_start(end)
    settlement_records = list(
        await context.session.scalars(
            select(SettlementRecord)
            .where(
                SettlementRecord.store_id == context.store.id,
                or_(
                    SettlementRecord.opening_month.between(first_month, last_month),
                    SettlementRecord.status == "pending",
                ),
            )
            .order_by(SettlementRecord.opening_month, SettlementRecord.id)
        )
    )
    company_names = {
        company_id: name
        for company_id, name in (
            await context.session.execute(
                select(SettlementCompany.id, SettlementCompany.name).where(
                    SettlementCompany.store_id == context.store.id
                )
            )
        ).tuples()
    }

    daily_by_month: dict[str, int] = {}
    for record_date, amount in daily_rows:
        month = record_date.strftime("%Y-%m")
        daily_by_month[month] = daily_by_month.get(month, 0) + int(amount)
    confirmed_by_month: dict[str, int] = {}
    for record in settlement_records:
        if record.status != "confirmed":
            continue
        month = record.opening_month.strftime("%Y-%m")
        confirmed_by_month[month] = confirmed_by_month.get(month, 0) + record.amount

    months = sorted(daily_by_month.keys() | confirmed_by_month.keys())
    monthly = []
    for month in months:
        daily_revenue = daily_by_month.get(month, 0)
        settlement_income = confirmed_by_month.get(month, 0)
        monthly.append(
            {
                "month": month,
                "daily_ledger_revenue": daily_revenue,
                "confirmed_settlement_income": settlement_income,
                "monthly_total_income": daily_revenue + settlement_income,
            }
        )
    daily_total = sum(daily_by_month.values())
    confirmed_total = sum(confirmed_by_month.values())
    pending_total = sum(
        record.amount for record in settlement_records if record.status == "pending"
    )
    return {
        "status": "success" if months or pending_total else "empty",
        "period": {
            "input": str(arguments["period"]).strip(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": context.store.timezone,
        },
        "daily_ledger_revenue": daily_total,
        "confirmed_settlement_income": confirmed_total,
        "total_income": daily_total + confirmed_total,
        "monthly": monthly,
        "current_pending_receivables": pending_total,
        "settlement_breakdown": _settlement_breakdown(
            settlement_records,
            group_by=group_by,
            first_month=first_month,
            last_month=last_month,
            company_names=company_names,
        ),
    }


def _category_ids(value: object) -> list[int] | str:
    if not isinstance(value, list) or not value:
        return "分类 ID 必须是非空数组"
    if len(value) > 50:
        return "一次最多查询 50 个分类"
    if any(not isinstance(item, int) or isinstance(item, bool) for item in value):
        return "分类 ID 必须是整数"
    if len(value) != len(set(value)):
        return "分类 ID 不能重复"
    return value


async def get_income_category_history(
    context: AuthorizedToolContext, arguments: Mapping[str, Any]
) -> JsonObject:
    resolved = _resolve_period(arguments.get("period"), local_today=context.local_today)
    if isinstance(resolved, str):
        return {"status": "error", "error": resolved}
    category_ids = _category_ids(arguments.get("category_ids"))
    if isinstance(category_ids, str):
        return {"status": "error", "error": category_ids}
    start, end = resolved

    records = list(
        (
            await context.session.execute(
                select(
                    StoreDailyRecord.id,
                    StoreDailyRecord.income_mode,
                    StoreDailyRecord.daily_revenue,
                )
                .where(
                    StoreDailyRecord.store_id == context.store.id,
                    StoreDailyRecord.date.between(start, end),
                )
                .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
            )
        ).tuples()
    )
    item_rows = list(
        (
            await context.session.execute(
                select(
                    DailyIncomeItem.category_id,
                    DailyIncomeItem.category_name,
                    DailyIncomeItem.include_in_total,
                    DailyIncomeItem.amount,
                )
                .join(
                    StoreDailyRecord,
                    StoreDailyRecord.id == DailyIncomeItem.record_id,
                )
                .where(
                    StoreDailyRecord.store_id == context.store.id,
                    StoreDailyRecord.date.between(start, end),
                    DailyIncomeItem.category_id.in_(category_ids),
                )
                .order_by(StoreDailyRecord.date, DailyIncomeItem.sort_order)
            )
        ).tuples()
    )
    known_ids = set(
        await context.session.scalars(
            select(IncomeCategory.id).where(
                IncomeCategory.store_id == context.store.id,
                IncomeCategory.id.in_(category_ids),
            )
        )
    )
    known_ids.update(row.category_id for row in item_rows)

    totals: dict[HistoricalCategorySnapshot, int] = {}
    for row in item_rows:
        key = HistoricalCategorySnapshot(
            category_id=row.category_id,
            category_name=row.category_name,
            include_in_total=row.include_in_total,
        )
        totals[key] = totals.get(key, 0) + row.amount
    requested_order = {category_id: index for index, category_id in enumerate(category_ids)}
    historical_composition = [
        {
            "category_id": snapshot.category_id,
            "category_name": snapshot.category_name,
            "include_in_total": snapshot.include_in_total,
            "amount": amount,
        }
        for snapshot, amount in sorted(
            totals.items(),
            key=lambda item: (
                requested_order[item[0].category_id],
                item[0].category_name,
                not item[0].include_in_total,
            ),
        )
    ]
    categorized = [record for record in records if record.income_mode == "composed"]
    total_only = [record for record in records if record.income_mode == "legacy_total"]
    selected_total = sum(row.amount for row in item_rows)
    selected_included = sum(
        row.amount for row in item_rows if row.include_in_total
    )
    return {
        "status": "success" if item_rows else "partial" if records else "empty",
        "period": {
            "input": str(arguments["period"]).strip(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": context.store.timezone,
        },
        "requested_category_ids": category_ids,
        "unmatched_category_ids": [
            category_id for category_id in category_ids if category_id not in known_ids
        ],
        "historical_composition": historical_composition,
        "selected_categories_total": selected_total,
        "selected_included_revenue": selected_included,
        "selected_other_data": selected_total - selected_included,
        "categorized_bookkeeping": {
            "record_count": len(categorized),
            "daily_ledger_revenue": sum(
                record.daily_revenue for record in categorized
            ),
        },
        "total_bookkeeping": {
            "record_count": len(total_only),
            "daily_ledger_revenue": sum(record.daily_revenue for record in total_only),
        },
        "period_daily_ledger_revenue": sum(
            record.daily_revenue for record in records
        ),
    }


def _daily_summary(records: Sequence[JsonObject]) -> JsonObject:
    operating_days = [record for record in records if record["is_operating_day"]]
    covered_operating_days = [
        record for record in operating_days if record["wash_count_covered"]
    ]
    daily_revenue = sum(int(record["daily_ledger_revenue"]) for record in records)
    operating_revenue = sum(
        int(record["daily_ledger_revenue"]) for record in operating_days
    )
    covered_revenue = sum(
        int(record["daily_ledger_revenue"]) for record in covered_operating_days
    )
    wash_count = sum(int(record["wash_count"]) for record in covered_operating_days)
    return {
        "record_count": len(records),
        "operating_day_count": len(operating_days),
        "daily_ledger_revenue": daily_revenue,
        "operating_day_average_revenue": (
            operating_revenue / len(operating_days) if operating_days else None
        ),
        "wash_count_coverage": {
            "covered_operating_days": len(covered_operating_days),
            "operating_days": len(operating_days),
            "wash_count": wash_count,
        },
        "average_revenue_per_wash": (
            covered_revenue / wash_count if wash_count else None
        ),
    }


def _daily_query(
    arguments: Mapping[str, Any],
) -> tuple[dict[str, Any], DailyGroup | None] | str:
    raw_filters = arguments.get("filters", {})
    if not isinstance(raw_filters, dict):
        return "每日台账筛选条件必须是对象"
    if not set(raw_filters).issubset(DAILY_FILTERS):
        return "每日台账筛选条件包含不支持的字段"
    filters = dict(raw_filters)
    for dimension in DAILY_DIMENSIONS:
        if dimension.filter_name not in filters:
            continue
        values = filters[dimension.filter_name]
        if dimension.schema["type"] == "boolean":
            if not isinstance(values, bool):
                return f"{dimension.filter_name} 筛选值必须是布尔值"
            continue
        if not isinstance(values, list) or not values or len(values) > 50:
            return f"{dimension.filter_name} 筛选值必须是 1 至 50 项的数组"
        if len(values) != len({json.dumps(value, ensure_ascii=False) for value in values}):
            return f"{dimension.filter_name} 筛选值不能重复"
        if dimension.allowed_values is not None and not set(values).issubset(
            dimension.allowed_values
        ):
            return f"{dimension.filter_name} 筛选值无效"
        if dimension.filter_name == "recorded_weather" and any(
            value is not None and not isinstance(value, str) for value in values
        ):
            return "recorded_weather 筛选值必须是文本或 null"

    raw_group_by = arguments.get("group_by")
    if raw_group_by is not None and raw_group_by not in DAILY_DIMENSIONS_BY_GROUP:
        return "每日台账分组方式无效"
    return filters, cast(DailyGroup | None, raw_group_by)


def _matches_daily_filters(record: JsonObject, filters: Mapping[str, Any]) -> bool:
    return all(
        (
            record[DAILY_DIMENSIONS_BY_FILTER[cast(DailyFilter, name)].record_key]
            in value
            if isinstance(value, list)
            else record[DAILY_DIMENSIONS_BY_FILTER[cast(DailyFilter, name)].record_key]
            == value
        )
        for name, value in filters.items()
    )


def _daily_groups(records: Sequence[JsonObject], group_by: DailyGroup) -> list[JsonObject]:
    dimension = DAILY_DIMENSIONS_BY_GROUP[group_by]
    grouped: dict[object, list[JsonObject]] = {}
    for record in records:
        grouped.setdefault(record[dimension.record_key], []).append(record)

    def sort_key(value: object) -> object:
        if dimension.sort_order is not None:
            return dimension.sort_order.index(value)
        if dimension.group_name == "recorded_weather":
            return value is None, str(value or "")
        return bool(value)

    return [
        {
            "dimension": group_by,
            "value": value,
            "summary": _daily_summary(grouped[value]),
        }
        for value in sorted(grouped, key=sort_key)
    ]


async def get_daily_ledger_data(
    context: AuthorizedToolContext, arguments: Mapping[str, Any]
) -> JsonObject:
    resolved = _resolve_period(arguments.get("period"), local_today=context.local_today)
    if isinstance(resolved, str):
        return {"status": "error", "error": resolved}
    query = _daily_query(arguments)
    if isinstance(query, str):
        return {"status": "error", "error": query}
    filters, group_by = query
    start, end = resolved
    record_rows = list(
        (
            await context.session.execute(
                select(
                    StoreDailyRecord.id,
                    StoreDailyRecord.date,
                    StoreDailyRecord.daily_revenue,
                    StoreDailyRecord.is_open,
                    StoreDailyRecord.wash_count,
                    StoreDailyRecord.weather,
                    StoreDailyRecord.activity,
                )
                .where(
                    StoreDailyRecord.store_id == context.store.id,
                    StoreDailyRecord.date.between(start, end),
                )
                .order_by(StoreDailyRecord.date, StoreDailyRecord.id)
            )
        ).tuples()
    )
    item_rows = list(
        (
            await context.session.execute(
                select(
                    DailyIncomeItem.record_id,
                    DailyIncomeItem.category_id,
                    DailyIncomeItem.category_name,
                    DailyIncomeItem.include_in_total,
                    DailyIncomeItem.amount,
                )
                .join(StoreDailyRecord, StoreDailyRecord.id == DailyIncomeItem.record_id)
                .where(
                    StoreDailyRecord.store_id == context.store.id,
                    StoreDailyRecord.date.between(start, end),
                )
                .order_by(
                    StoreDailyRecord.date,
                    DailyIncomeItem.sort_order,
                    DailyIncomeItem.id,
                )
            )
        ).tuples()
    )
    items_by_record: dict[int, list[JsonObject]] = {}
    for item in item_rows:
        items_by_record.setdefault(item.record_id, []).append(
            {
                "category_id": item.category_id,
                "category_name": item.category_name,
                "include_in_total": item.include_in_total,
                "amount": item.amount,
            }
        )
    records: list[JsonObject] = []
    for row in record_rows:
        event = row.activity
        records.append(
            {
                "date": row.date.isoformat(),
                "weekday": WEEKDAYS[row.date.weekday()],
                "operating_status": row.is_open,
                "is_operating_day": row.is_open in OPERATING_DAY_STATUSES,
                "daily_ledger_revenue": row.daily_revenue,
                "income_categories": items_by_record.get(row.id, []),
                "wash_count": row.wash_count,
                "wash_count_covered": row.wash_count is not None,
                "recorded_weather": row.weather,
                "event": event,
                "has_event": bool(event and event.strip()),
            }
        )
    filtered_records = [
        record for record in records if _matches_daily_filters(record, filters)
    ]
    result = {
        "status": "success" if records else "empty",
        "period": {
            "input": str(arguments["period"]).strip(),
            "start": start.isoformat(),
            "end": end.isoformat(),
            "timezone": context.store.timezone,
        },
        "summary": _daily_summary(filtered_records),
    }
    if filters or group_by is not None:
        result["query"] = {"filters": filters, "group_by": group_by}
    if group_by is None:
        result["records"] = filtered_records
    else:
        result["groups"] = _daily_groups(filtered_records, group_by)
    if not filtered_records:
        result["status"] = "empty"
    return result

DEFAULT_AGENT_TOOLS = AgentToolRegistry(
    [
        AgentTool(
            name="get_store_data_catalog",
            description=(
                "读取认证用户当前授权门店的记账设置、收入分类、营业额计入口径、"
                "可用经营字段和数据覆盖范围。门店由后端锁定，不接受门店参数。"
            ),
            parameters={
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
            handler=get_store_data_catalog,
        ),
        AgentTool(
            name="get_period_revenue",
            description=(
                "按门店当地日期解析期间，汇总每日台账营业额、已确认公司结算收入、"
                "月度总收入和独立的当前待到账应收款。可按公司、开票月份或状态分组。"
                "门店和当地今天由后端锁定。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": (
                            "用户要求的期间，例如上个月、今年、最近三周，或"
                            "2026-07-01 至 2026-07-31"
                        ),
                    },
                    "settlement_group_by": {
                        "type": "string",
                        "enum": ["company", "opening_month", "status"],
                    },
                },
                "required": ["period"],
                "additionalProperties": False,
            },
            handler=get_period_revenue,
        ),
        AgentTool(
            name="get_income_category_history",
            description=(
                "按分类 ID 查询指定期间的历史收入构成，由后端使用每条每日台账保存的"
                "分类名称和计入口径计算组合金额，并区分分类记账、总额记账、收入分类"
                "与其他数据。使用可信的当前分类 ID；尚未取得时可查询门店数据目录。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": (
                            "用户要求的期间，例如上个月、今年、最近三周，或"
                            "2026-07-01 至 2026-07-31"
                        ),
                    },
                    "category_ids": {
                        "type": "array",
                        "items": {"type": "integer"},
                        "minItems": 1,
                        "maxItems": 50,
                        "uniqueItems": True,
                        "description": (
                            "当前门店的可信分类 ID；缺少当前映射时可先查询门店数据目录。"
                        ),
                    },
                },
                "required": ["period", "category_ids"],
                "additionalProperties": False,
            },
            handler=get_income_category_history,
        ),
        AgentTool(
            name="get_daily_ledger_data",
            description=(
                "读取后端确认日期范围内的完整每日台账经营字段和由日期派生的星期，"
                "可按营业状态、星期、记录天气、是否有事件和洗车数量覆盖筛选或分组，"
                "并计算经营日与有洗车数量覆盖经营日的汇总指标。门店和当地今天由后端锁定。"
            ),
            parameters={
                "type": "object",
                "properties": {
                    "period": {
                        "type": "string",
                        "description": (
                            "用户要求的期间，例如上个月、今年、最近三周，或"
                            "2026-07-01 至 2026-07-31"
                        ),
                    },
                    "filters": {
                        "type": "object",
                        "properties": {
                            dimension.filter_name: dimension.schema
                            for dimension in DAILY_DIMENSIONS
                        },
                        "additionalProperties": False,
                    },
                    "group_by": {
                        "type": "string",
                        "enum": [
                            dimension.group_name for dimension in DAILY_DIMENSIONS
                        ],
                    },
                },
                "required": ["period"],
                "additionalProperties": False,
            },
            handler=get_daily_ledger_data,
        ),
    ]
)
