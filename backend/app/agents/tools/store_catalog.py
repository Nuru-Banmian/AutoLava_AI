"""Controlled domains; catalog snapshots never authorize a business query."""
import hashlib
import json
from calendar import monthrange
from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.agents.tools.query_definitions import GROUP_METADATA, GROUPS, METRICS
from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, StoreDailyRecord
from app.models.settlement import SettlementRecord

# Field metadata: type, unit, meaning. Database names are never published.
LEDGER_FIELDS = {
    "date": ["date", "day", "当地自然日"],
    "is_open": ["string", None, "营业/提前休息/休息/未统计"],
    "daily_revenue": ["integer?", "EUR", "台账额，不含结算；未统计为空"],
    "wash_count": ["integer?", "辆", "记录洗车数量"],
    "weather": ["string?", None, "记录天气"],
    "activity": ["string?", None, "完整事件，不推断收入覆盖日期"],
}
ITEM_FIELDS = {
    "date": ["date", "day", "当地自然日"],
    "category_id": ["integer", None, "历史分类标识"],
    "category_name": ["string", None, "保存时名称，保留归档历史"],
    "include_in_total": ["boolean", None, "计入台账额；其他数据不代表成本/利润"],
    "amount": ["integer", "EUR", "历史分类金额"],
}
FILTERS = ["eq", "in", "gte", "lte", "contains", "is_null", "not_null"]


class CatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def local_today(store):
    return datetime.now(ZoneInfo(store.timezone)).date()


def version(store):
    value = ["store-query-v2", store.timezone, store.income_items_enabled,
             store.wash_count_enabled, store.company_settlement_enabled, store.income_config_revision]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()[:24]


def fields_for(store, domain):
    if domain == "daily_ledger":
        return {k: v for k, v in LEDGER_FIELDS.items()
                if k != "wash_count" or store.wash_count_enabled}
    return ITEM_FIELDS if domain == "income_items" else {}


class CatalogCache:
    def __init__(self):
        self.values = {}

    def put(self, scope, generation, value):
        key = (scope.user_id, scope.store_id)
        self.values[key] = (generation, json.dumps(value, ensure_ascii=False))

    def get(self, scope, generation, current_version):
        entry = self.values.get((scope.user_id, scope.store_id))
        if entry and entry[0] == generation:
            value = json.loads(entry[1])
            if value["catalog_version"] == current_version:
                return value
        return None

    def clear(self, scope):
        self.values.pop((scope.user_id, scope.store_id), None)


async def date_snapshot(session, store_id, domain, *, record_dates=None):
    if domain not in METRICS:
        raise ValueError("Unknown catalog domain")
    if record_dates is None:
        record = StoreDailyRecord
        statement = select(func.min(record.date), func.max(record.date)).where(record.store_id == store_id)
        if domain == "income_items":
            statement = statement.join(DailyIncomeItem, DailyIncomeItem.record_id == record.id)
        first, last = (await session.execute(statement)).one()
    else:
        first, last = (date.fromisoformat(record_dates[name]) if record_dates[name] else None
                       for name in ("start", "end"))
    if domain in ("monthly_income", "income_composition"):
        settlement_first, settlement_last = (await session.execute(
            select(func.min(SettlementRecord.opening_month),
                   func.max(SettlementRecord.opening_month)).where(
                SettlementRecord.store_id == store_id,
                SettlementRecord.status == "confirmed",
            )
        )).one()
        if settlement_first:
            first = min(first, settlement_first) if first else settlement_first
            settlement_end = settlement_last.replace(
                day=monthrange(settlement_last.year, settlement_last.month)[1])
            last = max(last, settlement_end) if last else settlement_end
    return {"start": first.isoformat() if first else None, "end": last.isoformat() if last else None}


async def store_data_catalog(session, context, arguments):
    store = await session.get(Store, context.scope.store_id)
    result = {"schema_version": "v2", "catalog_version": version(store),
              "observed_at": datetime.now(ZoneInfo(store.timezone)).isoformat(),
              "timezone": store.timezone, "domains": {},
              "metric_metadata": {name: info for metrics in METRICS.values()
                                  for name, info in metrics.items()},
              "group_metadata": GROUP_METADATA, "filters": FILTERS}
    grains = {"daily_ledger": "day", "income_items": "day/category",
              "monthly_income": "month", "income_composition": "month/category"}
    dates = {domain: await date_snapshot(session, store.id, domain)
             for domain in ("daily_ledger", "income_items")}
    dates["monthly_income"] = await date_snapshot(
        session, store.id, "monthly_income", record_dates=dates["daily_ledger"])
    dates["income_composition"] = dates["monthly_income"]
    filter_fields = {"daily_ledger": "daily_ledger+weekday", "income_items": "daily_ledger+income_items+weekday",
                     "monthly_income": "daily_ledger+weekday",
                     "income_composition": "daily_ledger+category+weekday"}
    for domain in METRICS:
        result["domains"][domain] = {"fields": fields_for(store, domain), "grain": grains[domain],
                                    "filter_fields": filter_fields[domain],
                                    "metrics": list(METRICS[domain]), "group_by": GROUPS[domain],
                                    "dates": dates[domain]}
    result["notes"] = (
        "fields/metrics互斥；汇总fields=[]。至多2分组且1日历维。filter_fields引用域fields；category引用"
        "分类属性。默认本月至今；全历史重查无366天限。当前期截至今日，完整期按"
        "自然边界；比较给出双方范围与未完期。未统计/未录入未知，集中收入不分摊。"
    )
    context.catalogs.put(context.scope, context.generation, result)
    return result
