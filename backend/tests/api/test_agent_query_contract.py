"""The provider must receive the target identity needed by the real query API."""
from app.agents.registry import capabilities
from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_store_query import QueryModel
from tests.api.test_agent_tools import ask


async def test_month_only_followup_rejects_stale_range_before_query(tmp_path, monkeypatch):
    from datetime import date
    from tests.api.test_agent_store_query import query
    monkeypatch.setattr("app.agents.tools.store_query.local_today", lambda _: date(2026, 10, 10))
    wrong = query([{"id": "old", "domain": "daily_ledger", "metrics": ["total_revenue"],
                    "range": {"start": "2026-09-01", "end": "2026-09-30"}}])
    right = query([{"id": "new", "domain": "daily_ledger", "metrics": ["total_revenue"],
                    "range": {"start": "2026-08-01", "end": "2026-08-31"}}])
    def repair(observed):
        failure = observed.results[-1]
        assert failure["error"] == "query_range_required"
        assert failure["required_range"] == {"start": "2026-08-01", "end": "2026-08-31"}
        assert "targets" not in failure
        return right(observed)
    model = QueryModel([("store_data_catalog", {}), wrong, repair, "已重新查询八月。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "上上个月的呢")
        assert run["status"] == "completed", run
        assert "已重新查询八月" in run["output"]


def test_provider_query_schema_requires_target_id_and_domain():
    _, tools = capabilities()
    schema = next(t["function"]["parameters"] for t in tools.schemas
                  if t["function"]["name"] == "store_query")
    target = schema["properties"]["targets"]["items"]
    assert {"id", "domain"}.issubset(target.get("required", []))
    assert set(target["properties"]["domain"]["enum"]) == {
        "daily_ledger", "income_items", "monthly_income", "income_composition",
    }
    assert target["additionalProperties"] is False
    assert "all_history" not in target["properties"]
    assert "all_history" in schema["$defs"]["DateRange"]["properties"]
    assert {"range", "filters", "compare", "order_by", "row_limit"}.issubset(target["properties"])
    assert len(target["oneOf"]) == 2


def test_comparison_schema_directs_provider_to_backend_changes():
    _, tools = capabilities()
    schema = next(t["function"]["parameters"] for t in tools.schemas
                  if t["function"]["name"] == "store_query")
    compare = schema["properties"]["targets"]["items"]["properties"]["compare"]
    assert "comparison.changes" in compare.get("description", "")
    assert "difference" in compare["description"] and "change_percent" in compare["description"]


def test_provider_schema_has_no_continuation_or_page_size():
    import json
    from app.agents.tools.store_query import QueryInput
    schema = QueryInput.model_json_schema()
    assert "continuations" not in schema["properties"]
    assert "page_size" not in json.dumps(schema)
    assert set(schema["required"]) == {"catalog_version", "targets"}


def test_chart_schema_preserves_numeric_series_guidance():
    _, tools = capabilities()
    schema = next(t["function"]["parameters"] for t in tools.schemas
                  if t["function"]["name"] == "store_chart")
    assert "series:[amount]" in schema["properties"]["series"].get("description", "")
    assert "only" in schema["properties"]["block"].get("description", "")


async def test_missing_target_identity_tells_model_how_to_repair(tmp_path):
    model = QueryModel([
        ("store_query", {"catalog_version": "missing", "targets": [
            {"domain": "monthly_income", "metrics": ["total_income"]},
        ]}),
    ])
    # A general route can report the invalid argument without inventing business evidence.
    from tests.api.test_agent_chat import StreamingModel
    model.stream_plan = StreamingModel().stream_plan
    def reply(observed):
        error = observed.results[-1]
        assert error["error"] == "invalid_tool_arguments"
        assert "id" in error["message"] and "domain" in error["message"]
        return "目标参数不完整，请补充。"
    model.actions = iter([("store_query", {"catalog_version": "missing", "targets": [
        {"domain": "monthly_income", "metrics": ["total_income"]},
    ]}), reply])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client))["status"] == "completed"


async def test_explicit_missing_record_date_is_queried_before_claiming_unrecorded(tmp_path):
    from tests.api.test_agent_store_query import query
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "known", "domain": "daily_ledger", "range": {"start": "2026-06-18", "end": "2026-06-20"},
        "fields": ["date", "is_open", "daily_revenue"],
    }]), "9月30日超出目录，已经确定未录入。", query([{
        "id": "missing", "domain": "daily_ledger", "range": {"start": "2026-09-30", "end": "2026-09-30"},
        "fields": ["date", "is_open", "daily_revenue"],
    }]), "三天都已查询；9月30日没有记录，未录入。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "查询2026年6月20日、6月18日和9月30日的金额与状态")
        assert run["status"] == "completed", run
        assert "超出目录" not in run["output"]
        target = model.results[-1]["targets"][0]
        assert target["range"] == {"start": "2026-09-30", "end": "2026-09-30"}
        assert target["matched_count"] == 0
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert "超出目录" not in events and events.count('"name": "store_query"') == 2


async def test_requested_difference_uses_backend_comparison_before_answer(tmp_path):
    from tests.api.test_agent_store_query import query
    from tests.api.test_agent_tools import save_day
    july = {"id": "july", "domain": "daily_ledger", "range": {"start": "2026-07-01", "end": "2026-07-31"},
            "metrics": ["total_revenue"]}
    june = {**july, "id": "june", "range": {"start": "2026-06-01", "end": "2026-06-30"}}
    model = QueryModel([("store_data_catalog", {}), query([july, june]),
        "模型自行计算差额20、变化率20%。",
        query([{**july, "compare": {"range": june["range"]}}]), "后端差额20欧元，变化率20%。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-06-01", 100)
        await save_day(client, "2026-07-01", 120)
        run = await ask(client, "比较2026年7月与6月台账营业额，给出差额和变化率")
        assert run["status"] == "completed", run
        assert "模型自行计算" not in run["output"]
        change = model.results[-1]["targets"][0]["comparison"]["changes"]["total_revenue"]
        assert change["difference"] == 20 and change["change_percent"] == 20


async def test_default_context_fits_three_small_monthly_summaries(tmp_path):
    from tests.api.test_agent_store_query import query
    from tests.api.test_agent_tools import save_day
    model = QueryModel([
        ("read_skill_resource", {"skill": "store-analysis", "path": "references/metrics.md"}),
        ("store_data_catalog", {}), query([
            {"id": month, "domain": "monthly_income",
             "range": {"start": f"2026-{month}-01", "end": f"2026-{month}-30"},
             "metrics": ["daily_ledger_revenue", "confirmed_settlement_income", "total_income",
                         "monthly_average_income"]}
            for month in ("06", "07", "08")
        ]), "三个小型月度汇总均已完成。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-06-01", 100)
        configured = await client.put("/api/admin/stores/1/income-config", json={
            "expected_revision": 1, "enabled": True, "items": [
                {"name": "现金", "include_in_total": True},
                {"name": "刷卡", "include_in_total": True},
                {"name": "设备读数", "include_in_total": False},
            ],
        })
        assert configured.status_code == 200
        assert (await ask(client))["status"] == "completed"
        result = model.results[-1]
        assert result["status"] == "complete", result
        assert all(t["status"] == "complete" for t in result["targets"])
        assert result["targets"][0]["metrics"]["daily_ledger_revenue"] == 100


async def test_string_targets_are_rejected_then_correct_array_can_query(tmp_path):
    import json
    from tests.api.test_agent_store_query import query, catalog
    target = {"id": "historical", "domain": "daily_ledger",
              "range": {"start": "2026-06-20", "end": "2026-06-20"},
              "fields": ["date", "is_open", "daily_revenue"]}
    def malformed(model):
        return "store_query", {"catalog_version": catalog(model)["catalog_version"],
                               "targets": json.dumps([target])}
    model = QueryModel([("store_data_catalog", {}), malformed, query([target]), "最新查询无记录，未录入。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "查询2026年6月20日状态，不用图")
        assert run["status"] == "completed", run
        assert model.results[2]["error"] == "invalid_tool_arguments"
        assert "JSON array" in model.results[2]["message"]
        assert '"targets":[{' in model.results[2]["message"]
        assert model.results[-1]["targets"][0]["matched_count"] == 0
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert "invalid_tool_arguments" in events


async def test_two_month_chart_queries_both_months_and_saves_both_values(tmp_path):
    from tests.api.test_agent_store_query import query
    from tests.api.test_agent_tools import save_day
    from tests.api.test_agent_saved_charts import saved_chart
    def chart(model):
        return "store_chart", {"operation": "create", "result_ref": model.results[-1]["targets"][0]["result_ref"],
            "dimension": "month", "series": ["total_revenue"], "type": "grouped_bar", "title": "两月台账"}
    model = QueryModel([("store_data_catalog", {}), query([{
        "id": "both", "domain": "daily_ledger", "range": {"start": "2026-06-01", "end": "2026-07-31"},
        "metrics": ["total_revenue"], "group_by": ["month"]}]), chart, "两月图已生成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client, "2026-06-01", 100)
        await save_day(client, "2026-07-01", 120)
        run = await ask(client, "用分组柱状图比较2026年7月和6月台账营业额")
        assert run["status"] == "completed", run
        message, chart_id = await saved_chart(client)
        payload = (await client.get(f"/api/agent/1/messages/{message}/charts/{chart_id}")).json()["payload"]
        assert [(p["dimension"], p["values"]["total_revenue"]["exact"]) for p in payload["points"]] == [
            ("2026-06", "100"), ("2026-07", "120")]


async def test_removed_continuation_is_rejected_then_new_range_query_succeeds(tmp_path):
    from tests.api.test_agent_store_query import query
    model = QueryModel([("store_data_catalog", {}),
                        ("store_query", {"continuations":[{"result_ref":"0"*32,"cursor":"old"}]}),
                        query([{"id":"days","domain":"daily_ledger",
                                "range":{"start":"2026-07-01","end":"2026-07-02"},
                                "metrics":["total_revenue"],"group_by":["day"]}]),
                        "重新查询两天，未录入。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "查询两天台账营业额")
        assert run["status"] == "completed", run
        receipt = next(r for r in model.results if r.get("error"))
        assert receipt["error"] == "invalid_tool_arguments"
        assert "smaller date range" in receipt["message"]
        target = model.results[-1]["targets"][0]
        assert len(target["rows"]) == 2
        assert "next_cursor" not in target


async def test_default_month_income_rejects_daily_breakdown_before_business_read(tmp_path):
    from tests.api.test_agent_store_query import query
    from tests.api.test_agent_tools import save_day
    base = {"id":"income", "domain":"monthly_income", "range":{"start":"2026-07-01","end":"2026-07-31"},
            "metrics":["total_income"]}
    model = QueryModel([("store_data_catalog", {}), query([{**base,"domain":"daily_ledger",
                        "metrics":["total_revenue"],"group_by":["day"]}]),
                        query([base]), "7月收入100欧元。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client,"2026-07-01",100)
        run = await ask(client,"查询2026年7月收入")
        assert run["status"] == "completed", run
        assert model.results[2]["error"] == "query_granularity_required"
        target = model.results[-1]["targets"][0]
        assert target["rows"] == [] and target["metrics"]["total_income"] == 100


async def test_default_year_income_rejects_monthly_breakdown(tmp_path):
    from tests.api.test_agent_store_query import query
    from tests.api.test_agent_tools import save_day
    base = {"id":"year", "domain":"monthly_income", "range":{"start":"2025-01-01","end":"2025-12-31"},
            "metrics":["total_income"]}
    model = QueryModel([("store_data_catalog", {}), query([{**base,"group_by":["month"]}]), query([base]), "全年收入100欧元。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client,"2025-07-01",100)
        run = await ask(client,"查询2025年收入")
        assert run["status"] == "completed", run
        assert model.results[2]["error"] == "query_granularity_required"
        target = model.results[-1]["targets"][0]
        assert target["rows"] == [] and target["metrics"]["total_income"] == 100


async def test_week_trend_and_explicit_year_drilldown_keep_requested_grain(tmp_path):
    from tests.api.test_agent_store_query import query
    from tests.api.test_agent_tools import save_day
    week = {"id":"week", "domain":"daily_ledger", "range":{"start":"2026-07-06","end":"2026-07-12"},
            "metrics":["total_revenue"], "group_by":["day"]}
    year = {"id":"months", "domain":"monthly_income", "range":{"start":"2026-01-01","end":"2026-12-31"},
            "metrics":["total_income"], "group_by":["month"]}
    model = QueryModel([("store_data_catalog", {}), query([week]), "一周每天收入已查询。",
                        ("store_data_catalog", {}), query([year]), "全年按月已拆分。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        await save_day(client,"2026-07-06",100)
        run = await ask(client,"查询2026年7月6日至12日一周每天台账收入")
        assert run["status"] == "completed", run
        target = model.results[-1]["targets"][0]
        assert len(target["rows"]) == 7 and target["rows"][0]["metrics"]["total_revenue"] == 100
        run = await ask(client,"再细分2026年收入，按月列出")
        assert run["status"] == "completed", run
        assert any(row.get("month") == "2026-07" and row["metrics"]["total_income"] == 100
                   for r in model.results for t in r.get("targets", []) for row in t.get("rows", []))


async def test_compare_chart_cannot_publish_only_main_month(tmp_path):
    from tests.api.test_agent_store_query import query
    from tests.api.test_agent_tools import save_day
    def incomplete(model):
        return "store_chart", {"operation":"create","result_ref":model.results[-1]["targets"][0]["result_ref"],
            "dimension":"month","series":["total_revenue"],"type":"grouped_bar","title":"6月与7月比較"}
    model=QueryModel([("store_data_catalog",{}),query([{
        "id":"compare","domain":"daily_ledger","range":{"start":"2026-07-01","end":"2026-07-31"},
        "metrics":["total_revenue"],"group_by":["month"],
        "compare":{"range":{"start":"2026-06-01","end":"2026-06-30"}}}]),incomplete,"双月图未生成，需重新查询跨两月分组。"])
    async with chat_app(tmp_path,model) as (client,_,_):
        await save_day(client,"2026-06-01",100)
        await save_day(client,"2026-07-01",120)
        run=await ask(client,"用分组柱状图比较2026年7月和6月台账营业额")
        assert run["status"] == "completed",run
        assert model.results[-1]["error"] == "chart_periods_missing"
        assert model.results[-1]["required_months"] == ["2026-06","2026-07"]
        conversation=(await client.get('/api/agent/1/conversation')).json()
        assert not conversation['messages'][-1]['charts']


async def test_category_stack_cannot_substitute_total_for_cash_and_card(tmp_path):
    from tests.api.test_agent_store_query import query
    from tests.api.test_agent_tools import save_day
    def incomplete(model):
        return "store_chart", {"operation":"create","result_ref":model.results[-1]["targets"][0]["result_ref"],
            "dimension":"month","series":["daily_ledger_revenue","confirmed_settlement_income"],
            "type":"stacked_bar","title":"现金刷卡构成"}
    model=QueryModel([("store_data_catalog",{}),query([{
        "id":"total","domain":"monthly_income","range":{"start":"2026-07-01","end":"2026-07-31"},
        "metrics":["daily_ledger_revenue","confirmed_settlement_income"],"group_by":["month"]}]),
        incomplete,"分类图未生成，需查询各分类。"])
    async with chat_app(tmp_path,model) as (client,_,_):
        enabled=await client.patch('/api/admin/stores/1',json={"expected_description_revision":1,
                                  "description":"分类图验收门店","company_settlement_enabled":True})
        assert enabled.status_code == 200,enabled.text
        await save_day(client,"2026-07-01",120)
        run=await ask(client,"画2026年7月现金、刷卡收入构成的堆叠柱状图")
        assert run["status"] == "completed",run
        assert model.results[-1]["error"] == "chart_categories_missing"
        conversation=(await client.get('/api/agent/1/conversation')).json()
        assert not conversation['messages'][-1]['charts']
