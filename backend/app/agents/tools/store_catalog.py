"""Controlled domains; catalog snapshots never authorize a business query."""
import hashlib
import json
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from app.models.identity import Store
from app.models.ledger import DailyIncomeItem, StoreDailyRecord

# Field metadata: type, unit, meaning. Database names are never published.
LEDGER_FIELDS = {
    "date": ["date", "day", "当地自然日"],
    "is_open": ["string", None, "营业/提前休息/休息/未统计"],
    "daily_revenue": ["integer?", "EUR", "台账营业额，不含公司结算；未统计为空"],
    "wash_count": ["integer?", "辆", "记录洗车数量"],
    "weather": ["string?", None, "记录天气"],
    "activity": ["string?", None, "完整事件，不能推断集中收入覆盖日期"],
}
ITEM_FIELDS = {
    "date": ["date", "day", "当地自然日"],
    "category_id": ["integer", None, "历史分类标识"],
    "category_name": ["string", None, "保存时的历史分类名称，包括已归档分类"],
    "include_in_total": ["boolean", None, "是否计入台账营业额；其他数据不等于成本或利润"],
    "amount": ["integer", "EUR", "历史分类金额"],
}
FILTERS = ["eq", "in", "gte", "lte", "contains", "is_null", "not_null"]


class CatalogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def local_today(store):
    return datetime.now(ZoneInfo(store.timezone)).date()


def version(store):
    value = ["store-query-v1", store.timezone, store.income_items_enabled,
             store.wash_count_enabled, store.company_settlement_enabled, store.income_config_revision]
    return hashlib.sha256(json.dumps(value).encode()).hexdigest()[:24]


def fields_for(store, domain):
    return ({k: v for k, v in LEDGER_FIELDS.items() if k != "wash_count" or store.wash_count_enabled}
            if domain == "daily_ledger" else ITEM_FIELDS)


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


async def date_snapshot(session, store_id, domain):
    record = StoreDailyRecord
    statement = select(func.min(record.date), func.max(record.date)).where(record.store_id == store_id)
    if domain == "income_items":
        statement = statement.join(DailyIncomeItem, DailyIncomeItem.record_id == record.id)
    first, last = (await session.execute(statement)).one()
    return {"start": first.isoformat() if first else None, "end": last.isoformat() if last else None}


async def store_data_catalog(session, context, arguments):
    store = await session.get(Store, context.scope.store_id)
    result = {"catalog_version": version(store), "observed_at": datetime.now(ZoneInfo(store.timezone)).isoformat(),
              "timezone": store.timezone, "domains": {}}
    for domain in ("daily_ledger", "income_items"):
        result["domains"][domain] = {"fields": fields_for(store, domain), "grain": "day" if domain == "daily_ledger" else "day/category",
                                    "filters": FILTERS, "metrics": [], "group_by": [],
                                    "dates": await date_snapshot(session, store.id, domain)}
    result["notes"] = "日期为观察快照；每次查询重新检查授权、范围及数据。仅上线明细；分组/指标与月度收入待后续工单。无范围默认本月至今，全部历史不限366天。"
    context.catalogs.put(context.scope, context.generation, result)
    return result
