"""Month-grain Agent income through authenticated chat and migrated SQLite."""

from datetime import datetime

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_store_query import QueryModel, cached_catalog, query
from tests.api.test_agent_tools import ask, save_day
from tests.api.test_charts_daily_migrated import confirm_settlement


async def test_recent_three_months_income_and_composition_in_one_query(tmp_path, monkeypatch):
    import app.agents.tools.store_catalog as catalog_module

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 9, 12, tzinfo=tz)

    monkeypatch.setattr(catalog_module, "datetime", Clock)
    model = QueryModel([
        ("store_data_catalog", {}), query([
            {"id": "income", "domain": "monthly_income", "range": {"preset": "last_n_months", "n": 3},
             "metrics": ["daily_ledger_revenue", "confirmed_settlement_income", "total_income"],
             "group_by": ["month"]},
            {"id": "composition", "domain": "income_composition", "range": {"preset": "last_n_months", "n": 3},
             "metrics": ["amount", "share_percent"], "group_by": ["month", "category"]},
        ]), "三个月收入及构成已查询；十月台账尚未统计，结算按开票月份计入。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-08-01", 150)
        assert (await client.patch("/api/admin/stores/1", json={
            "company_settlement_enabled": True})).status_code == 200
        configured = await client.put("/api/admin/stores/1/income-config", json={
            "expected_revision": 1, "enabled": True,
            "items": [{"name": "现金", "include_in_total": True},
                      {"name": "刷卡", "include_in_total": True},
                      {"name": "其他数据", "include_in_total": False}],
        })
        assert configured.status_code == 200, configured.text
        config = configured.json()
        cash, card, other = config["items"]
        for day, state, values in [
            ("2026-09-01", "营业", [25, 75, 900]),
            ("2026-10-01", "未统计", None),
        ]:
            saved = await client.put(f"/api/ledger/1/{day}", json={
                "expected_identity": None, "expected_revision": None,
                "expected_config_revision": config["revision"], "is_open": state,
                "daily_revenue": None, "items": [] if values is None else [
                    {"category_id": category["id"], "amount": amount}
                    for category, amount in zip((cash, card, other), values, strict=True)],
            })
            assert saved.status_code == 201, saved.text
        await confirm_settlement(client, 1, "2026-09", 200)
        await confirm_settlement(client, 1, "2026-10", 400)
        assert (await client.patch("/api/admin/stores/1", json={
            "company_settlement_enabled": False})).status_code == 200
        run = await ask(client, "最近三个月各月收入及构成")
        assert run["status"] == "completed", (run, model.results)
        batch = model.results[-1]
        assert batch["status"] == "complete", batch
        income, composition = batch["targets"]
        assert [(row["month"], row["metrics"]) for row in income["rows"]] == [
            ("2026-08", {"daily_ledger_revenue": 150, "confirmed_settlement_income": 0, "total_income": 150}),
            ("2026-09", {"daily_ledger_revenue": 100, "confirmed_settlement_income": 200, "total_income": 300}),
            ("2026-10", {"daily_ledger_revenue": None, "confirmed_settlement_income": 400, "total_income": 400}),
        ]
        assert income["metrics"]["total_income"] == 850
        assert income["coverage"]["unreported_days"] == 1
        assert income["rows"][-1]["metric_status"]["daily_ledger_revenue"] == "no_statistical_ledger"
        rows = {(row["month"], row["category_name"]): row for row in composition["rows"]}
        assert set(rows) == {("2026-08", "未分类营业额"), ("2026-09", "现金"),
                             ("2026-09", "刷卡"), ("2026-09", "公司结算"), ("2026-10", "公司结算")}
        assert rows[("2026-09", "现金")]["metrics"] == {"amount": 25, "share_percent": 8.33}
        assert rows[("2026-09", "现金")]["denominators"]["share_percent"] == 300
        assert rows[("2026-09", "刷卡")]["metrics"] == {"amount": 75, "share_percent": 25.0}
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert events.count('"name": "store_query"') == 1
        assert '"name": "store_overview"' not in events


async def test_unreported_month_is_unknown_and_known_zero_remains_zero(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "unknown", "domain": "monthly_income", "range": {"start": "2026-07-01", "end": "2026-07-31"},
         "metrics": ["daily_ledger_revenue", "total_income", "monthly_average_income"]},
        {"id": "other_unknown", "domain": "income_composition", "range": {"start": "2026-07-01", "end": "2026-07-31"},
         "metrics": ["amount", "share_percent"],
         "filters": [{"field": "include_in_total", "op": "eq", "value": False}]},
        {"id": "zero", "domain": "monthly_income", "range": {"start": "2026-08-01", "end": "2026-08-31"},
         "metrics": ["daily_ledger_revenue", "total_income", "monthly_average_income"]},
    ]), "七月尚未统计；八月有已知零收入，不能把两者混同。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-10", None, "未统计")
        await save_day(client, "2026-08-10", 0)
        run = await ask(client)
        assert run["status"] == "completed", (run, model.results)
        unknown, other, zero = model.results[-1]["targets"]
        assert unknown["metrics"] == {"daily_ledger_revenue": None, "total_income": None,
                                      "monthly_average_income": None}
        assert unknown["metric_status"]["total_income"] == "no_statistical_ledger"
        assert other["metrics"] == {"amount": None, "share_percent": None}
        assert set(other["metric_status"].values()) == {"no_statistical_ledger"}
        assert zero["metrics"] == {"daily_ledger_revenue": 0, "total_income": 0,
                                   "monthly_average_income": 0}
        assert set(zero["metric_status"].values()) == {"available"}


async def test_partial_month_whole_settlement_and_year_totals_keep_selected_grain(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "partial", "domain": "monthly_income", "range": {"start": "2026-07-02", "end": "2026-07-02"},
         "metrics": ["total_income", "monthly_average_income"]},
        {"id": "month", "domain": "monthly_income", "range": {"start": "2026-07-01", "end": "2026-07-31"},
         "metrics": ["total_income", "monthly_average_income"]},
        {"id": "year", "domain": "monthly_income", "range": {"start": "2026-07-01", "end": "2026-08-31"},
         "metrics": ["total_income", "monthly_average_income"], "group_by": ["year"]},
        {"id": "composition_month", "domain": "income_composition",
         "range": {"start": "2026-07-01", "end": "2026-07-31"},
         "metrics": ["amount", "share_percent"], "group_by": ["month"]},
    ]), "七月局部台账仍计整月结算；年度各月收入汇总，未重复计入。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await client.patch("/api/admin/stores/1", json={
            "company_settlement_enabled": True})).status_code == 200
        await save_day(client, "2026-07-01", 100)
        await save_day(client, "2026-07-02", 50)
        await save_day(client, "2026-08-01", 25)
        await confirm_settlement(client, 1, "2026-07", 300)
        await confirm_settlement(client, 1, "2026-08", 25)
        run = await ask(client)
        assert run["status"] == "completed", (run, model.results)
        partial, month, year, composition = model.results[-1]["targets"]
        assert partial["metrics"]["total_income"] == 350
        assert partial["settlement_months"] == ["2026-07"]
        assert partial["partial_months"] == ["2026-07"]
        assert partial["metric_status"]["monthly_average_income"] == "invalid_monthly_range"
        assert month["metrics"] == {"total_income": 450, "monthly_average_income": 225}
        assert year["metrics"]["total_income"] == 500
        assert year["metric_status"]["monthly_average_income"] == "invalid_monthly_range"
        assert len(year["rows"]) == 1 and year["rows"][0]["metrics"]["total_income"] == 500
        assert len(composition["rows"]) == 1
        assert composition["rows"][0]["month"] == "2026-07"
        assert composition["rows"][0]["metrics"] == {"amount": 450, "share_percent": 100.0}
        assert "category_name" not in composition["rows"][0]


async def test_monthly_amount_and_quantity_read_only_their_dependencies(tmp_path):
    from sqlalchemy import event

    model = QueryModel([
        ("store_data_catalog", {}), query([{"id": "first", "domain": "daily_ledger", "fields": ["date"]}]),
        "目录已取得。",
        lambda m: ("store_query", {"catalog_version": cached_catalog(m)["catalog_version"], "targets": [
            {"id": "money", "domain": "monthly_income", "range": {"start": "2026-07-01", "end": "2026-07-31"},
             "metrics": ["daily_ledger_revenue"]},
            {"id": "cars", "domain": "monthly_income", "range": {"start": "2026-07-01", "end": "2026-07-31"},
             "metrics": ["total_wash_count", "average_revenue_per_car"]},
        ]}), "台账150欧元，3辆，平均每车50欧元；没有查询公司结算。",
    ])
    async with chat_app(tmp_path, model) as (client, _, factory):
        await save_day(client, "2026-07-10", 150, wash=3)
        assert (await ask(client))["status"] == "completed"
        engine, projections = factory.kw["bind"].sync_engine, []

        def observe(connection, cursor, statement, parameters, context, many):
            sql = statement.lower()
            if sql.startswith("select"):
                assert "settlement_records" not in sql, "Unrequested settlement domain was accessed"
                assert "daily_income_items" not in sql, "Unrequested category domain was accessed"
                if "from store_daily_records" in sql:
                    projections.append(sql)
                    assert "store_daily_records.activity" not in sql
                    assert "store_daily_records.weather" not in sql

        event.listen(engine, "before_cursor_execute", observe)
        try:
            run = await ask(client, "只查七月台账额和洗车数量")
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert run["status"] == "completed", (run, model.results)
        money, cars = model.results[-1]["targets"]
        assert money["metrics"] == {"daily_ledger_revenue": 150}
        assert cars["metrics"] == {"total_wash_count": 3, "average_revenue_per_car": 50}
        assert projections
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"name": "store_data_catalog"' not in events


async def test_monthly_average_does_not_use_a_filtered_subset_of_the_month(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "filtered", "domain": "monthly_income", "range": {"start": "2026-07-01", "end": "2026-07-31"},
         "metrics": ["total_income", "monthly_average_income"], "group_by": ["month"],
         "filters": [{"field": "daily_revenue", "op": "gte", "value": 100}]},
    ]), "筛选后的台账与整月结算可报告，完整月份的月度日均收入不可由子集代表。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 125)
        await save_day(client, "2026-07-02", 75)
        assert (await client.patch("/api/admin/stores/1", json={
            "company_settlement_enabled": True})).status_code == 200
        await confirm_settlement(client, 1, "2026-07", 100)
        run = await ask(client)
        assert run["status"] == "completed", (run, model.results)
        result = model.results[-1]["targets"][0]
        assert result["metrics"] == {"total_income": 225, "monthly_average_income": None}
        assert result["metric_status"]["monthly_average_income"] == "filtered_monthly_range"
        assert result["rows"][0]["metric_status"]["monthly_average_income"] == "filtered_monthly_range"
        assert result["coverage"]["excluded_record_days"] == 1
        assert result["coverage"]["missing_record_days"] == 29


async def test_settlement_only_history_uses_opening_month_and_no_ledger_amount(tmp_path):
    from sqlalchemy import event

    model = QueryModel([
        ("store_data_catalog", {}), query([{"id": "first", "domain": "daily_ledger", "fields": ["date"]}]),
        "目录已取得。",
        lambda m: ("store_query", {"catalog_version": cached_catalog(m)["catalog_version"], "targets": [
            {"id": "settlement", "domain": "monthly_income", "range": {"all_history": True},
             "metrics": ["confirmed_settlement_income"]},
        ]}), "只有已确认公司结算，归属于1999年开票月份，不能声称有台账。",
    ])
    async with chat_app(tmp_path, model) as (client, _, factory):
        assert (await client.patch("/api/admin/stores/1", json={
            "company_settlement_enabled": True})).status_code == 200
        await confirm_settlement(client, 1, "1999-01", 250)
        assert (await client.patch("/api/admin/stores/1", json={
            "company_settlement_enabled": False})).status_code == 200
        assert (await ask(client))["status"] == "completed"
        engine, projections = factory.kw["bind"].sync_engine, []

        def observe(connection, cursor, statement, parameters, context, many):
            sql = statement.lower()
            if sql.startswith("select") and "from store_daily_records" in sql:
                projections.append(sql)
                assert "store_daily_records.daily_revenue" not in sql
                assert "store_daily_records.wash_count" not in sql
                assert "store_daily_records.activity" not in sql
                assert "store_daily_records.weather" not in sql

        event.listen(engine, "before_cursor_execute", observe)
        try:
            run = await ask(client, "全部历史已确认公司结算")
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert run["status"] == "completed", (run, model.results)
        result = model.results[-1]["targets"][0]
        assert result["range"]["start"] == "1999-01-01"
        assert result["metrics"] == {"confirmed_settlement_income": 250}
        assert result["coverage"]["record_days"] == 0
        assert projections


async def test_composition_historical_category_filters_keep_other_data_separate(tmp_path):
    model = QueryModel([])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-07-01", 150)
        configured = await client.put("/api/admin/stores/1/income-config", json={
            "expected_revision": 1, "enabled": True,
            "items": [{"name": "现金", "include_in_total": True},
                      {"name": "其他数据", "include_in_total": False}],
        })
        assert configured.status_code == 200, configured.text
        config = configured.json()
        cash, other = config["items"]
        saved = await client.put("/api/ledger/1/2026-07-02", json={
            "expected_identity": None, "expected_revision": None,
            "expected_config_revision": config["revision"], "is_open": "营业",
            "items": [{"category_id": cash["id"], "amount": 25},
                      {"category_id": other["id"], "amount": 900}],
        })
        assert saved.status_code == 201, saved.text
        renamed = await client.patch(f"/api/admin/income-categories/{cash['id']}", json={
            "expected_revision": config["revision"], "name": "后来名称", "include_in_total": False})
        assert renamed.status_code == 200, renamed.text
        current = (await client.get("/api/admin/stores/1/income-config")).json()
        archived = await client.post(f"/api/admin/income-categories/{cash['id']}/archive", json={
            "expected_revision": current["revision"]})
        assert archived.status_code == 200, archived.text
        current = (await client.get("/api/admin/stores/1/income-config")).json()
        disabled = await client.put("/api/admin/stores/1/income-config", json={
            "expected_revision": current["revision"], "enabled": False, "items": []})
        assert disabled.status_code == 200, disabled.text
        model.actions = iter([("store_data_catalog", {}), query([
            {"id": "cash", "domain": "income_composition", "range": {"all_history": True},
             "metrics": ["amount", "share_percent"],
             "filters": [{"field": "category_id", "op": "eq", "value": cash["id"]}]},
            {"id": "other_id", "domain": "income_composition", "range": {"all_history": True},
             "metrics": ["amount", "share_percent"],
             "filters": [{"field": "category_id", "op": "eq", "value": other["id"]}]},
            {"id": "other_flag", "domain": "income_composition", "range": {"all_history": True},
             "metrics": ["amount", "share_percent"],
             "filters": [{"field": "include_in_total", "op": "in", "value": [False]}]},
        ]), "历史现金仍按保存时名称与含义查询；其他数据独立，不作为收入或成本。"])
        run = await ask(client)
        assert run["status"] == "completed", (run, model.results)
        cash_result, other_id, other_flag = model.results[-1]["targets"]
        assert cash_result["metrics"] == {"amount": 25, "share_percent": 14.29}
        assert cash_result["rows"][0]["category_name"] == "现金"
        assert cash_result["rows"][0]["include_in_total"] is True
        assert cash_result["denominators"]["share_percent"] == 175
        for result in (other_id, other_flag):
            assert result["metrics"] == {"amount": 900, "share_percent": 100.0}
            assert result["denominator_scope"] == "categorical_other"
            assert result["denominators"]["share_percent"] == 900
            assert len(result["rows"]) == 1 and result["rows"][0]["source"] == "other_data"
