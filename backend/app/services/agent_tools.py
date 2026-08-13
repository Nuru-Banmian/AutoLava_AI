import json
import re
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Literal, cast
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.orm.attributes import InstrumentedAttribute
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store
from app.models.ledger import IncomeCategory, StoreDailyRecord
from app.models.settlement import SettlementCompany, SettlementRecord
from app.services.access import require_fresh_store_access
from app.services.income_config import IncomeConfigService

JsonObject = dict[str, Any]
SettlementGroup = Literal["company", "opening_month", "status"]


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
    ]
)
