import json
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Store
from app.models.ledger import IncomeCategory, StoreDailyRecord
from app.models.settlement import SettlementRecord
from app.services.access import require_fresh_store_access
from app.services.income_config import IncomeConfigService

JsonObject = dict[str, Any]


@dataclass(frozen=True)
class AgentToolContext:
    session: AsyncSession
    user_id: int
    store_id: int


@dataclass(frozen=True)
class AuthorizedToolContext:
    session: AsyncSession
    user_id: int
    store: Store


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
    daily_coverage = (
        await session.execute(
            select(
                func.count(StoreDailyRecord.id),
                func.min(StoreDailyRecord.date),
                func.max(StoreDailyRecord.date),
            ).where(StoreDailyRecord.store_id == store.id)
        )
    ).one()
    wash_coverage = (
        await session.execute(
            select(
                func.count(StoreDailyRecord.id),
                func.min(StoreDailyRecord.date),
                func.max(StoreDailyRecord.date),
            ).where(
                StoreDailyRecord.store_id == store.id,
                StoreDailyRecord.wash_count.is_not(None),
            )
        )
    ).one()
    weather_coverage = (
        await session.execute(
            select(
                func.count(StoreDailyRecord.id),
                func.min(StoreDailyRecord.date),
                func.max(StoreDailyRecord.date),
            ).where(
                StoreDailyRecord.store_id == store.id,
                StoreDailyRecord.weather.is_not(None),
            )
        )
    ).one()
    event_coverage = (
        await session.execute(
            select(
                func.count(StoreDailyRecord.id),
                func.min(StoreDailyRecord.date),
                func.max(StoreDailyRecord.date),
            ).where(
                StoreDailyRecord.store_id == store.id,
                StoreDailyRecord.activity.is_not(None),
            )
        )
    ).one()
    settlement_coverage = (
        await session.execute(
            select(
                func.count(SettlementRecord.id),
                func.min(SettlementRecord.opening_month),
                func.max(SettlementRecord.opening_month),
            ).where(SettlementRecord.store_id == store.id)
        )
    ).one()
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
            "daily_records": _coverage(daily_coverage),
            "wash_count": _coverage(wash_coverage),
            "recorded_weather": _coverage(weather_coverage),
            "events": _coverage(event_coverage),
            "company_settlement": _coverage(settlement_coverage),
        },
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
        )
    ]
)
