"""Historical classification aggregates through authenticated chat and migrated SQLite."""

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_query_metrics import freeze_today
from tests.api.test_agent_store_query import QueryModel, query
from tests.api.test_agent_tools import ask


async def income_config(client):
    response = await client.put("/api/admin/stores/1/income-config", json={
        "expected_revision": 1, "enabled": True,
        "items": [{"name": "现金", "include_in_total": True, "sort_order": 0},
                  {"name": "刷卡", "include_in_total": True, "sort_order": 1},
                  {"name": "其他数据", "include_in_total": False, "sort_order": 2}],
    })
    assert response.status_code == 200, response.text
    return response.json()


async def save_categories(client, config, day, amounts, **attributes):
    response = await client.put(f"/api/ledger/1/{day}", json={
        "expected_identity": None, "expected_revision": None,
        "expected_config_revision": config["revision"], "is_open": "营业",
        "items": [{"category_id": category["id"], "amount": amount}
                  for category, amount in zip(config["items"], amounts)], **attributes,
    })
    assert response.status_code == 201, response.text


async def test_category_shares_use_month_and_income_status_with_historical_names(tmp_path, monkeypatch):
    freeze_today(monkeypatch)
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "categories", "domain": "income_items",
        "range": {"start": "2026-07-01", "end": "2026-08-31"},
        "metrics": ["amount", "share_percent"], "group_by": ["month", "category"],
    }]), "分类占比按月计算，其他数据使用独立分母，历史名称保留。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        config = await income_config(client)
        await save_categories(client, config, "2026-07-01", [100, 300, 50])
        await save_categories(client, config, "2026-08-01", [200, 0, 25])
        cash = config["items"][0]
        renamed = await client.patch(f"/api/admin/income-categories/{cash['id']}", json={
            "expected_revision": config["revision"], "name": "后来现金名称",
        })
        assert renamed.status_code == 200, renamed.text
        current = (await client.get("/api/admin/stores/1/income-config")).json()
        archived = await client.post(f"/api/admin/income-categories/{cash['id']}/archive", json={
            "expected_revision": current["revision"],
        })
        assert archived.status_code == 200, archived.text
        run = await ask(client, "七月八月各收入分类及其他数据的金额占比")
        assert run["status"] == "completed", run
        result = model.results[-1]["targets"][0]
        assert result["status"] == "complete", result
        rows = {(row["month"], row["category_name"]): row for row in result["rows"]}
        expected = {
            ("2026-07", "现金"): (100, 25.0, 400),
            ("2026-07", "刷卡"): (300, 75.0, 400),
            ("2026-07", "其他数据"): (50, 100.0, 50),
            ("2026-08", "现金"): (200, 100.0, 200),
            ("2026-08", "刷卡"): (0, 0.0, 200),
            ("2026-08", "其他数据"): (25, 100.0, 25),
        }
        assert set(rows) == set(expected)
        for key, (amount, share, denominator) in expected.items():
            assert rows[key]["metrics"] == {"amount": amount, "share_percent": share}
            assert rows[key]["denominators"]["share_percent"] == denominator
            assert rows[key]["category"] == key[1]
            assert rows[key]["include_in_total"] == (key[1] != "其他数据")
        assert result["coverage"]["base_scope"] == "same_filters_and_non_category_groups_by_include_in_total"
        assert result["matched_count"] == 6
        events = await client.get(f"/api/agent/1/runs/{run['id']}/events")
        assert events.text.count('"name": "store_query"') == 1


async def test_filtered_category_shares_and_amounts_read_only_projected_dependencies(tmp_path, monkeypatch):
    from sqlalchemy import event

    freeze_today(monkeypatch)
    observe = {"active": False}
    targets = []

    def start_query(model):
        observe["active"] = True
        return query(targets)(model)

    model = QueryModel([("store_data_catalog", {}), start_query,
                        "已按筛选条件计算分类金额及占比，分母也遵循同一筛选范围。"])
    async with chat_app(tmp_path, model) as (client, _, factory):
        config = await income_config(client)
        await save_categories(client, config, "2026-07-01", [100, 300, 50], weather="晴")
        await save_categories(client, config, "2026-07-02", [900, 0, 100], weather="阴")
        current = (await client.get("/api/admin/stores/1/income-config")).json()
        disabled = await client.put("/api/admin/stores/1/income-config", json={
            "expected_revision": current["revision"], "enabled": False, "items": [],
        })
        assert disabled.status_code == 200, disabled.text
        selected = {"start": "2026-07-01", "end": "2026-07-02"}
        targets.extend([
            {"id": "weather", "domain": "income_items", "range": selected,
             "metrics": ["amount", "share_percent"], "group_by": ["category"],
             "filters": [{"field": "weather", "op": "eq", "value": "晴"},
                         {"field": "weekday", "op": "eq", "value": 2}]},
            {"id": "cash", "domain": "income_items", "range": selected,
             "metrics": ["amount", "share_percent"], "group_by": ["category"],
             "filters": [{"field": "category_id", "op": "eq", "value": config["items"][0]["id"]}]},
            {"id": "amount", "domain": "income_items", "range": selected, "metrics": ["amount"],
             "filters": [{"field": "include_in_total", "op": "eq", "value": True}]},
        ])
        statements = []

        def record_sql(connection, cursor, statement, parameters, context, many):
            if observe["active"] and statement.lstrip().lower().startswith("select"):
                statements.append(statement.lower())

        engine = factory.kw["bind"].sync_engine
        event.listen(engine, "before_cursor_execute", record_sql)
        try:
            run = await ask(client, "按晴天星期三及现金分类筛选占比，再查历史收入类金额")
        finally:
            event.remove(engine, "before_cursor_execute", record_sql)
        assert run["status"] == "completed", run
        weather, cash, amount = model.results[-1]["targets"]
        assert all(result["status"] == "complete" for result in (weather, cash, amount))
        rows = {row["category_name"]: row for row in weather["rows"]}
        assert rows["现金"]["metrics"] == {"amount": 100, "share_percent": 25.0}
        assert rows["刷卡"]["metrics"] == {"amount": 300, "share_percent": 75.0}
        assert rows["其他数据"]["denominators"]["share_percent"] == 50
        assert cash["rows"][0]["metrics"] == {"amount": 1000, "share_percent": 100.0}
        assert cash["rows"][0]["denominators"]["share_percent"] == 1000
        assert cash["coverage"]["base_scope"] == "same_filters_and_non_category_groups_by_include_in_total"
        assert amount["metrics"] == {"amount": 1300}
        assert amount["denominators"] == {}
        ledger_selects = [sql for sql in statements if "store_daily_records" in sql]
        assert ledger_selects
        assert not any("settlement_records" in sql or "income_categories" in sql for sql in statements)
        for sql in ledger_selects:
            projection = sql.partition("from")[0]
            assert "daily_revenue" not in projection
            assert "activity" not in projection
            assert "wash_count" not in projection
            assert "weather" not in projection


async def test_zero_category_denominators_remain_unavailable_and_empty_scope_is_unknown(tmp_path, monkeypatch):
    freeze_today(monkeypatch)
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "zeros", "domain": "income_items", "range": {"all_history": True},
         "metrics": ["amount", "share_percent"], "group_by": ["category"]},
        {"id": "none", "domain": "income_items", "range": {"all_history": True},
         "metrics": ["amount", "share_percent"],
         "filters": [{"field": "category_name", "op": "eq", "value": "没有此分类"}]},
    ]), "已记录零金额，但零分母占比不可用；不存在的分类金额保持未知。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        config = await income_config(client)
        await save_categories(client, config, "2026-07-01", [0, 0, 0])
        run = await ask(client, "查询零金额分类的占比和不存在的分类")
        assert run["status"] == "completed", run
        zeros, empty = model.results[-1]["targets"]
        assert zeros["metrics"]["amount"] == 0
        assert len(zeros["rows"]) == 3
        for row in zeros["rows"]:
            assert row["metrics"] == {"amount": 0, "share_percent": None}
            assert row["metric_status"]["share_percent"] == "zero_denominator"
            assert row["denominators"]["share_percent"] == 0
        assert empty["metrics"] == {"amount": None, "share_percent": None}
        assert empty["metric_status"] == {
            "amount": "no_statistical_items", "share_percent": "no_statistical_items",
        }
        assert empty["denominators"]["share_percent"] == 0
        assert empty["coverage"]["record_days"] == 0
