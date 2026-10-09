"""Published business metrics and grouping dimensions for controlled queries."""

LEDGER_METRICS = {
    "total_revenue": ["EUR", "已统计台账营业额，不含公司结算"],
    "operating_days": ["天", "营业或提前休息日数"],
    "average_ledger_revenue": ["EUR", "经营日台账营业额/经营日数，四舍五入到整数欧元"],
    "total_wash_count": ["辆", "有数量记录的经营日洗车数量合计"],
    "average_revenue_per_car": ["EUR", "有数量记录的经营日台账营业额/洗车数量，整数欧元"],
    "min_revenue": ["EUR", "已统计日最低台账营业额，包含休息日零额"],
    "max_revenue": ["EUR", "已统计日最高台账营业额"],
}
ITEM_METRICS = {
    "amount": ["EUR", "对应收入口径金额合计"],
    "share_percent": ["%", "同期间同收入口径金额占比，保留两位小数；分母零时不可用"],
}
METRICS = {
    "daily_ledger": LEDGER_METRICS,
    "income_items": ITEM_METRICS,
    "monthly_income": {
        "daily_ledger_revenue": LEDGER_METRICS["total_revenue"],
        "confirmed_settlement_income": ["EUR", "重叠开票月份的整笔已确认结算；关闭功能仍含历史"],
        "total_income": ["EUR", "区间台账+重叠月份已确认结算，不分摊到日"],
        **{name: LEDGER_METRICS[name] for name in (
            "operating_days", "average_ledger_revenue", "total_wash_count", "average_revenue_per_car"
        )},
        "monthly_average_income": ["EUR", "单完整自然月或本月至今总收入/经营日数；其他区间不可用"],
    },
    "income_composition": ITEM_METRICS,
}
GROUPS = {
    "daily_ledger": ["day", "week", "month", "weather", "weekday"],
    "income_items": ["day", "week", "month", "category", "weather", "weekday"],
    "monthly_income": ["month", "year"],
    "income_composition": ["month", "year", "category"],
}
GROUP_METADATA = {
    "week": "当地周一日期",
    "weather": "记录天气；空值未记录",
    "weekday": "0..6对应周一..日",
    "category": "历史分类标识/名称/计入总额状态，保留归档历史",
}
