from datetime import date, datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.models.identity import Store
from app.services.analytics import AnalyticsService


class OverviewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    start: date
    end: date

    @field_validator("start", "end", mode="before")
    @classmethod
    def iso_date(cls, value):
        if not isinstance(value, str) or len(value) != 10:
            raise ValueError("Use YYYY-MM-DD")
        parsed = date.fromisoformat(value)
        if parsed.isoformat() != value:
            raise ValueError("Use YYYY-MM-DD")
        return parsed

    @model_validator(mode="after")
    def bounded_range(self):
        if not 0 <= (self.end - self.start).days < 366:
            raise ValueError("Query 1 to 366 days, start <= end")
        return self


async def store_overview(session, context, arguments: OverviewInput):
    scope = context.scope
    # Recheck at the tool boundary, independently of HTTP and model input.
    await scope.authorize(session)
    store = await session.get(Store, scope.store_id)
    today = datetime.now(ZoneInfo(store.timezone)).date()
    start, end = arguments.start, min(arguments.end, today)
    if start > end:
        return {"error": "invalid_date_range", "message": "开始日期不能晚于门店当地今天"}
    data = await AnalyticsService(session).calculate(
        store_id=scope.store_id, start=start, end=end, category_ids=None,
        company_settlement_enabled=store.company_settlement_enabled, local_date=today,
    )
    kpis, coverage = data["kpis"], data["period_coverage"]
    unavailable = []
    if not store.wash_count_enabled:
        unavailable.append("记录洗车数量已关闭；不使用历史洗车数量，不能据此判断是否存在历史记录")
        unavailable.append("平均每车收入不可用：记录洗车数量已关闭")
    elif kpis["average_ticket"] is None:
        unavailable.append("平均每车收入不可用：未记录洗车数量或合计为零")
    if not kpis["open_days"]:
        unavailable.append("经营日均台账营业额不可用：没有经营日")
    return {
        "source": "AnalyticsService", "store_id": scope.store_id, "currency": "EUR",
        "as_of_date": today.isoformat(),
        "requested_range": {"start": arguments.start.isoformat(), "end": arguments.end.isoformat()},
        "range": {"start": data["range"]["start"], "end": data["range"]["end"]},
        "income_summary": data["income_summary"],
        "metrics": {
            "operating_days": kpis["open_days"],
            "average_ledger_revenue": kpis["average_revenue"] if kpis["open_days"] else None,
            "total_wash_count": kpis["total_wash_count"],
            "average_revenue_per_car": kpis["average_ticket"],
        },
        "coverage": {
            "record_days": coverage["record_days"], "interval_days": coverage["interval_days"],
            "rest_days": coverage["record_days"] - kpis["open_days"],
            "missing_record_days": coverage["interval_days"] - coverage["record_days"],
            "wash_count_covered_days": kpis["wash_count_covered_days"],
            "wash_count_status": kpis["wash_count_coverage_status"],
            "wash_count_missing_operating_days": (
                kpis["open_days"] - kpis["wash_count_covered_days"] if store.wash_count_enabled else None
            ),
        },
        "unavailable": unavailable,
        "definitions": [
            "金额单位为整数欧元；平均值四舍五入到整数欧元。未来结束日期截到门店当地今天。",
            "经营日仅含营业与提前休息；休息不是经营日，未录入不当作零收入。",
            "经营日均台账营业额=经营日台账营业额合计/经营日数，不含公司结算。",
            "已确认公司结算按开票月份归属；查询与月份重叠即整笔纳入，关闭业务仍保留历史已确认收入。",
            "平均每车收入仅使用同时记录洗车数量的经营日台账营业额/洗车数量，不含公司结算；部分覆盖不能外推全期。",
            "本概览不计算任意局部期间的月度日均收入，不提供预测或因果结论。",
        ],
    }
