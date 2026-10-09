"""Authenticated chat / migrated SQLite acceptance for Issue #263."""
import json
import pytest
from uuid import uuid4

from app.agents.providers.bailian import ToolCall
from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_tools import ask


class QueryModel:
    model_name = "controlled-query-model"

    def __init__(self, actions):
        self.actions = iter(actions)
        self.results = []
        self.messages = []

    async def stream_plan(self, messages, tools):
        yield ToolCall("plan", "plan_response", '{"kind":"query","queries":[]}')

    async def stream_tools(self, messages, tools):
        self.messages.append(messages)
        self.results = [json.loads(m["content"]) for m in messages if m["role"] == "tool"]
        action = next(self.actions)
        if callable(action):
            action = action(self)
        if isinstance(action, str):
            yield action
        else:
            name, args = action
            yield ToolCall(uuid4().hex, name, json.dumps(args))


def catalog(model):
    return next(r for r in reversed(model.results) if "catalog_version" in r and "domains" in r)


def query(targets):
    return lambda model: ("store_query", {"catalog_version": catalog(model)["catalog_version"],
                                         "targets": targets})


async def test_catalog_and_top_five_preserve_complete_events(tmp_path):
    event = "清点多日收入，保留完整事件。" * 25
    model = QueryModel([
        ("store_data_catalog", {}),
        query([{"id": "highest", "domain": "daily_ledger", "range": {"all_history": True},
                "fields": ["date", "daily_revenue", "activity"],
                "order_by": [{"field": "daily_revenue", "direction": "desc"}], "top_n": 5}]),
        "已查询最高五天，金额记在清点当天。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day, amount in [(1, 100), (2, 300), (3, 300), (4, 20), (5, 50), (6, 0)]:
            response = await client.put(f"/api/ledger/1/2026-07-{day:02}", json={
                "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
                "is_open": "营业", "daily_revenue": amount, "activity": event,
            })
            assert response.status_code == 201, response.text
        run = await ask(client, "全部历史营业额最高五天和当天事件")
        assert run["status"] == "completed", run
        description = catalog(model)
        assert len(json.dumps(description, ensure_ascii=False)) <= 3000
        assert set(description["domains"]) == {"daily_ledger", "income_items", "monthly_income", "income_composition"}
        result = model.results[-1]
        assert result["status"] == "complete", result
        target = result["targets"][0]
        assert target["matched_count"] == 6 and target["selected_count"] == 5
        assert [row["date"] for row in target["rows"]] == [
            "2026-07-02", "2026-07-03", "2026-07-01", "2026-07-05", "2026-07-04"]
        assert all(row["activity"] == event for row in target["rows"])
        assert all(set(row) == {"date", "daily_revenue", "activity"} for row in target["rows"])
        events = await client.get(f"/api/agent/1/runs/{run['id']}/events")
        assert events.text.count('"name": "store_query"') == 1
        assert '"name": "store_overview"' not in events.text


def cached_catalog(model):
    from tests.api.test_agent_tools import background
    return background(model.messages[-1]).get("data_catalog")


async def test_second_turn_reuses_catalog_but_reads_new_history_boundary(tmp_path):
    model = QueryModel([
        ("store_data_catalog", {}), query([{"id": "first", "domain": "daily_ledger",
            "range": {"all_history": True}, "fields": ["date", "daily_revenue"]}]), "首轮查询完成。",
        lambda m: ("store_query", {"catalog_version": cached_catalog(m)["catalog_version"],
            "targets": [{"id": "second", "domain": "daily_ledger", "range": {"all_history": True},
                         "fields": ["date", "daily_revenue"]}]}), "已重新查询全部历史。",
    ])
    async with chat_app(tmp_path, model) as (client, _, _):
        from tests.api.test_agent_tools import save_day
        await save_day(client, "2026-07-10", 15)
        assert (await ask(client))["status"] == "completed"
        first_version = catalog(model)["catalog_version"]
        await save_day(client, "2020-01-01", 99)
        second = await ask(client, "再查全部历史")
        assert second["status"] == "completed", second
        assert cached_catalog(model)["catalog_version"] == first_version
        assert model.results[-1]["targets"][0]["range"]["start"] == "2020-01-01"
        assert model.results[-1]["targets"][0]["matched_count"] == 2
        events = await client.get(f"/api/agent/1/runs/{second['id']}/events")
        assert '"name": "store_data_catalog"' not in events.text
        assert '"name": "store_query"' in events.text


async def test_changed_config_rejects_entire_batch_and_invalidates_cached_description(tmp_path):
    remembered = {}
    def remember(m):
        remembered.update(catalog(m))
        return ("store_query", {"catalog_version": remembered["catalog_version"],
                                "targets": [{"id": "ok", "domain": "daily_ledger", "fields": ["date"]}]})
    model = QueryModel([("store_data_catalog", {}), remember, "首轮完成。",
        lambda m: ("store_query", {"catalog_version": remembered["catalog_version"],
                                  "targets": [{"id": "a", "domain": "daily_ledger", "fields": ["date"]},
                                              {"id": "b", "domain": "daily_ledger", "fields": ["wash_count"]}]}),
        "目录失效，整批未执行。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client))["status"] == "completed"
        updated = await client.patch("/api/admin/stores/1", json={"wash_count_enabled": False})
        assert updated.status_code == 200, updated.text
        failed_run = await ask(client)
        assert failed_run["status"] == "failed" and failed_run["error_code"] == "grounding_unavailable"
        assert "目录失效，整批未执行" not in failed_run["output"]
        assert cached_catalog(model) is None
        assert model.results[-1]["error"] == "catalog_stale"
        assert "targets" not in model.results[-1]
        assert model.results[-1]["catalog_version"] != remembered["catalog_version"]


async def test_partial_targets_literal_keywords_and_unknown_values(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "literal", "domain": "daily_ledger", "range": {"all_history": True},
         "fields": ["date", "activity"], "filters": [{"field": "activity", "op": "contains", "value": "%_"}]},
        {"id": "unknown", "domain": "daily_ledger", "fields": ["password"]},
        {"id": "nulls", "domain": "daily_ledger", "range": {"all_history": True},
         "fields": ["daily_revenue", "is_open"], "filters": [{"field": "daily_revenue", "op": "is_null"}]},
        {"id": "inject", "domain": "daily_ledger", "fields": ["date"], "sql": "select * from users"},
    ]), "部分目标完成，未统计金额未知。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        from tests.api.test_agent_tools import save_day
        await save_day(client, "2026-07-10", None, "未统计")
        for day, event in [(11, "literal %_"), (12, "anything"), (13, "x' OR 1=1 --")]:
            response = await client.put(f"/api/ledger/1/2026-07-{day}", json={
                "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
                "is_open": "营业", "daily_revenue": 0, "activity": event})
            assert response.status_code == 201
        assert (await ask(client))["status"] == "completed"
        batch = model.results[-1]
        assert batch["status"] == "partial"
        a, b, c, d = batch["targets"]
        assert a["rows"] == [{"date": "2026-07-11", "activity": "literal %_"}]
        assert b["error"] == d["error"] == "invalid_query_target"
        assert c["rows"] == [{"daily_revenue": None, "is_open": "未统计"}]


async def test_calendar_presets_leap_mapping_future_cutoff_and_default(tmp_path, monkeypatch):
    from datetime import datetime
    import app.agents.tools.store_catalog as catalog_module
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 10, 9, 12, tzinfo=tz)
    monkeypatch.setattr(catalog_module, "datetime", Clock)
    targets = [
        {"id": "recent", "domain": "daily_ledger", "fields": ["date"], "range": {"preset": "last_n_months", "n": 3}},
        {"id": "complete", "domain": "daily_ledger", "fields": ["date"], "range": {"preset": "last_n_complete_months", "n": 3}},
        {"id": "week", "domain": "daily_ledger", "fields": ["date"], "range": {"preset": "this_week"}},
        {"id": "leap", "domain": "daily_ledger", "fields": ["date"], "range": {"preset": "same_period_last_year", "base": {"start": "2024-02-29", "end": "2024-02-29"}}},
        {"id": "future", "domain": "daily_ledger", "fields": ["date"], "range": {"start": "2026-10-01", "end": "2026-12-31"}},
        {"id": "default", "domain": "daily_ledger", "fields": ["date"]},
    ]
    model = QueryModel([("store_data_catalog", {}), query(targets), "日期范围已核对。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client))["status"] == "completed"
        result = model.results[-1]
        assert result["status"] == "complete", result
        ranges = [t["range"] for t in result["targets"]]
        assert ranges == [
            {"start": "2026-08-01", "end": "2026-10-09"},
            {"start": "2026-07-01", "end": "2026-09-30"},
            {"start": "2026-10-05", "end": "2026-10-09"},
            {"start": "2023-02-28", "end": "2023-02-28"},
            {"start": "2026-10-01", "end": "2026-10-09"},
            {"start": "2026-10-01", "end": "2026-10-09"},
        ]
        assert result["targets"][4]["requested_range"]["end"] == "2026-12-31"
        assert "默认本月至今" in result["targets"][5]["notes"][0]


async def test_many_full_events_fail_without_truncation_and_keep_small_target(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "large", "domain": "daily_ledger", "range": {"all_history": True}, "fields": ["date", "activity"]},
        {"id": "small", "domain": "daily_ledger", "range": {"all_history": True}, "fields": ["date"], "top_n": 1},
    ]), "完整事件结果超容量；日期目标已完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day in range(1, 11):
            response = await client.put(f"/api/ledger/1/2026-07-{day:02}", json={
                "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
                "is_open": "营业", "daily_revenue": day, "activity": "完整事件" * 500})
            assert response.status_code == 201
        assert (await ask(client))["status"] == "completed"
        result = model.results[-1]
        assert result["status"] == "partial", result
        failed, success = result["targets"]
        assert failed["error"] == "result_capacity_exceeded"
        assert "rows" not in failed
        assert success["rows"] == [{"date": "2026-07-01"}]
        assert success["matched_count"] == 10 and success["selected_count"] == 1
        assert len(json.dumps(result, ensure_ascii=False)) <= 12000


async def test_history_category_snapshot_survives_rename_archive_and_disabled_mode(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "items", "domain": "income_items", "range": {"all_history": True},
         "fields": ["date", "category_id", "category_name", "include_in_total", "amount"]},
    ]), "历史其他数据保持原义。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        config = await client.put("/api/admin/stores/1/income-config", json={
            "expected_revision": 1, "enabled": True,
            "items": [{"name": "其他收入", "include_in_total": False, "sort_order": 0}]})
        assert config.status_code == 200, config.text
        data = config.json()
        category = data["items"][0]
        saved = await client.put("/api/ledger/1/2026-07-01", json={
            "expected_identity": None, "expected_revision": None, "expected_config_revision": data["revision"],
            "is_open": "营业", "items": [{"category_id": category["id"], "amount": 45}]})
        assert saved.status_code == 201, saved.text
        renamed = await client.patch(f"/api/admin/income-categories/{category['id']}", json={
            "expected_revision": data["revision"], "name": "后来名称"})
        assert renamed.status_code == 200, renamed.text
        current = (await client.get("/api/admin/stores/1/income-config")).json()
        archived = await client.post(f"/api/admin/income-categories/{category['id']}/archive", json={"expected_revision": current["revision"]})
        assert archived.status_code == 200, archived.text
        current = (await client.get("/api/admin/stores/1/income-config")).json()
        disabled = await client.put("/api/admin/stores/1/income-config", json={
            "expected_revision": current["revision"], "enabled": False, "items": []})
        assert disabled.status_code == 200, disabled.text
        assert (await ask(client))["status"] == "completed"
        result = model.results[-1]["targets"][0]
        assert result["rows"] == [{"date": "2026-07-01", "category_id": category["id"],
                                   "category_name": "其他收入", "include_in_total": False, "amount": 45}]


async def test_projection_queries_never_access_settlement_or_unselected_business_fields(tmp_path):
    from sqlalchemy import event
    from tests.api.test_agent_tools import save_day
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "money", "domain": "daily_ledger", "range": {"all_history": True},
         "fields": ["date", "daily_revenue"]},
        {"id": "cars", "domain": "daily_ledger", "range": {"all_history": True}, "fields": ["wash_count"]},
    ]), "仅查询金额和数量。"])
    async with chat_app(tmp_path, model) as (client, _, factory):
        await save_day(client, "2026-07-10", 10, wash=2)
        engine = factory.kw["bind"].sync_engine
        queries = []
        def observe(connection, cursor, statement, parameters, context, many):
            sql = statement.lower()
            if sql.startswith("select") and "store_daily_records" in sql:
                queries.append(sql)
            if sql.startswith("select") and ("from company_" in sql or "join company_" in sql):
                raise AssertionError("Unrelated settlement domain must not be queried")
        event.listen(engine, "before_cursor_execute", observe)
        try:
            assert (await ask(client))["status"] == "completed"
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert model.results[-1]["targets"][0]["rows"] == [{"date": "2026-07-10", "daily_revenue": 10}]
        assert model.results[-1]["targets"][1]["rows"] == [{"wash_count": 2}]
        assert queries and all("store_daily_records.activity" not in q and "store_daily_records.weather" not in q
                               for q in queries)



@pytest.mark.parametrize("change", [
    {"fields": ["date"] * 17},
    {"fields": ["date", "date"]},
    {"fields": ["date"], "filters": [{"field": "date", "op": "in", "value": ["2026-07-10"] * 51}]},
    {"fields": ["activity"], "filters": [{"field": "activity", "op": "contains", "value": "x" * 201}]},
    {"fields": ["daily_revenue"], "filters": [{"field": "daily_revenue", "op": "gte", "value": "0 OR 1=1"}]},
    {"fields": ["date"], "filters": [{"field": "date", "op": "eq", "value": "2026-07-10"}] * 9},
    {"fields": ["date"], "order_by": [{"field": "date"}] * 3},
    {"fields": ["date"], "top_n": 101},
    {"fields": ["date"], "top_n": True},
    {"fields": ["date"], "range": {"start": "2026-07-01", "end": "2026-07-10", "preset": "this_month"}},
    {"fields": ["date"], "range": {"preset": "last_n_months", "n": 0}},
    {"fields": ["date"], "range": {"all_history": False}},
    {"fields": ["date"], "group_by": ["date", "weather", "weekday"]},
    {"fields": ["date"], "metrics": ["total_income"]},
    {"fields": ["date"], "store_id": 2},
    {"fields": ["date"], "page_size": 1},
])
async def test_invalid_target_keeps_valid_neighbor(tmp_path, change):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "bad", "domain": "daily_ledger", **change},
        {"id": "good", "domain": "daily_ledger", "fields": ["date"]},
    ]), "无效目标拒绝，其他目标保留。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client))["status"] == "completed"
        result = model.results[-1]
        assert result["status"] == "partial", result
        assert result["targets"][0]["error"] == "invalid_query_target"
        assert result["targets"][1]["status"] == "complete"


async def test_catalog_cache_isolated_by_user_store_and_reset_generation(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([{"id": "one", "domain": "daily_ledger", "fields": ["date"]}]), "完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client))["status"] == "completed"
        # On each new route, inspect only the model-facing current background.
        def denied_without_catalog(m):
            assert cached_catalog(m) is None
            return "尚未查询，不应给出经营数值。"
        model.actions = iter([denied_without_catalog])
        await client.post("/api/auth/login", json={"username": "user-2", "password": "Password123"})
        result = await ask(client)
        assert result["error_code"] == "grounding_unavailable"
        await client.post("/api/auth/login", json={"username": "user-1", "password": "Password123"})
        assert (await client.post("/api/agent/1/conversation/reset", json={"generation": 0})).status_code == 200
        model.actions = iter([denied_without_catalog])
        assert (await ask(client))["error_code"] == "grounding_unavailable"
        model.actions = iter([denied_without_catalog])
        from tests.api.test_agent_chat import completed
        submitted = await client.post("/api/agent/2/messages", json={"request_id": uuid4().hex,
                                      "generation": 0, "content": "查门店乙"})
        assert submitted.status_code == 202
        assert (await completed(client, submitted.json()["id"], store=2))["error_code"] == "grounding_unavailable"


async def test_failed_query_cannot_publish_fabricated_business_value(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "bad", "domain": "daily_ledger", "fields": ["password"]},
    ]), "本轮营业额999欧元。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client)
        assert run["status"] == "failed" and run["error_code"] == "grounding_unavailable"
        assert "999" not in run["output"]
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["role"] == "user"


async def test_default_planning_does_not_advertise_legacy_business_route(tmp_path):
    class InspectPlan(QueryModel):
        async def stream_plan(self, messages, tools):
            enum = tools[0]["function"]["parameters"]["properties"]["kind"]["enum"]
            assert enum == ["general", "clarify", "query"]
            async for call in super().stream_plan(messages, tools):
                yield call
    model = InspectPlan([("store_data_catalog", {}), query([
        {"id": "ok", "domain": "daily_ledger", "fields": ["date"]},
    ]), "默认查询完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client))["status"] == "completed"


async def test_stale_catalog_refresh_retry_obtains_real_new_query_evidence(tmp_path):
    remembered = {}
    def first(m):
        remembered.update(catalog(m))
        return ("store_query", {"catalog_version": remembered["catalog_version"], "targets": [
            {"id": "first", "domain": "daily_ledger", "fields": ["date"]}]})
    model = QueryModel([("store_data_catalog", {}), first, "首次完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client))["status"] == "completed"
        assert (await client.patch("/api/admin/stores/1", json={"wash_count_enabled": False})).status_code == 200
        model.actions = iter([
            lambda m: ("store_query", {"catalog_version": remembered["catalog_version"], "targets": [
                {"id": "stale", "domain": "daily_ledger", "fields": ["date"]}]}),
            ("store_data_catalog", {}), query([{"id": "retry", "domain": "daily_ledger", "fields": ["date"]}]),
            "已刷新目录并重新查询。",
        ])
        run = await ask(client)
        assert run["status"] == "completed", run
        assert model.results[1]["error"] == "catalog_stale"
        assert model.results[-1]["status"] == "complete"
        assert "wash_count" not in catalog(model)["domains"]["daily_ledger"]["fields"]


@pytest.mark.parametrize("bad_batch", [
    {"targets": [{"id": "same", "domain": "daily_ledger", "fields": ["date"]}] * 2},
    {"targets": [{"id": str(i), "domain": "daily_ledger", "fields": ["date"]} for i in range(7)]},
    {"targets": [{"id": "one", "domain": "daily_ledger", "fields": ["date"]}], "store_id": 2},
])
async def test_invalid_batch_is_rejected_without_business_answer(tmp_path, bad_batch):
    model = QueryModel([("store_data_catalog", {}),
        lambda m: ("store_query", {"catalog_version": catalog(m)["catalog_version"], **bad_batch}),
        "伪造业务合计999欧元。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client)
        assert run["error_code"] == "grounding_unavailable"
        assert model.results[-1]["error"] == "invalid_tool_arguments"
        assert "999" not in run["output"]


@pytest.mark.parametrize("today,selection,expected", [
    ("2026-10-05", {"preset": "this_week"}, ("2026-10-05", "2026-10-05")),
    ("2026-10-05", {"preset": "last_week"}, ("2026-09-28", "2026-10-04")),
    ("2026-03-01", {"preset": "last_month"}, ("2026-02-01", "2026-02-28")),
    ("2024-03-01", {"preset": "last_month"}, ("2024-02-01", "2024-02-29")),
    ("2026-01-01", {"preset": "last_year"}, ("2025-01-01", "2025-12-31")),
    ("2026-10-09", {"preset": "last_n_complete_days", "n": 3}, ("2026-10-06", "2026-10-08")),
    ("2026-10-09", {"preset": "last_n_days", "n": 3}, ("2026-10-07", "2026-10-09")),
    ("2026-10-09", {"preset": "last_n_complete_weeks", "n": 2}, ("2026-09-21", "2026-10-04")),
    ("2026-10-09", {"preset": "last_n_weeks", "n": 2}, ("2026-09-28", "2026-10-09")),
    ("2026-10-09", {"preset": "same_period_last_year", "base": {"start": "2025-02-01", "end": "2025-02-28"}}, ("2024-02-01", "2024-02-29")),
])
async def test_local_calendar_edges_through_chat(tmp_path, monkeypatch, today, selection, expected):
    from datetime import datetime
    import app.agents.tools.store_catalog as module
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls.fromisoformat(today + "T12:00:00").replace(tzinfo=tz)
    monkeypatch.setattr(module, "datetime", Clock)
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "calendar", "domain": "daily_ledger", "fields": ["date"], "range": selection},
    ]), "已解析当地日期范围。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client)
        assert run["status"] == "completed", run
        assert model.results[-1]["targets"][0]["range"] == {"start": expected[0], "end": expected[1]}


@pytest.mark.parametrize("escaped", [False, True])
async def test_small_context_refuses_six_targets_before_business_reads(tmp_path, monkeypatch, escaped):
    from sqlalchemy import event
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "12000")
    queries = []
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": (str(index) + "\u0001" * 63) if escaped else str(index).zfill(64),
         "domain": "daily_ledger", "fields": ["date"]}
        for index in range(6)
    ]), "伪造业务合计999欧元。"])
    async with chat_app(tmp_path, model) as (client, _, factory):
        engine = factory.kw["bind"].sync_engine
        def observe(connection, cursor, statement, parameters, context, many):
            sql = statement.lower()
            if sql.startswith("select") and "from store_daily_records" in sql and "min(" not in sql:
                queries.append(sql)
        event.listen(engine, "before_cursor_execute", observe)
        try:
            run = await ask(client)
        finally:
            event.remove(engine, "before_cursor_execute", observe)
        assert run["error_code"] == "grounding_unavailable", run
        assert model.results[-1]["error"] == "context_capacity", model.results[-1]
        assert "targets" not in model.results[-1]
        assert not queries
        assert "999" not in run["output"]


async def test_large_first_target_reserves_escaped_neighbor_receipts(tmp_path, monkeypatch):
    monkeypatch.setenv("AUTOLAVA_AGENT_CONTEXT_CHARS", "64000")
    targets = [{"id": "large", "domain": "daily_ledger", "fields": ["date", "activity"],
                "range": {"all_history": True}, "top_n": 5}]
    targets += [{"id": str(i) + "\u0001" * 63, "domain": "daily_ledger", "fields": ["password"]}
                for i in range(1, 5)]
    targets += [{"id": "5" + "\u0001" * 63, "domain": "daily_ledger", "fields": ["date"],
                 "range": {"all_history": True}, "top_n": 1}]
    model = QueryModel([("store_data_catalog", {}), query(targets), "大目标无法完整返回；小目标成功。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day in range(1, 6):
            saved = await client.put(f"/api/ledger/1/2026-07-{day:02}", json={
                "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
                "is_open": "营业", "daily_revenue": day, "activity": "完整事件" * 475})
            assert saved.status_code == 201
        run = await ask(client)
        assert run["status"] == "completed", run
        batch = model.results[-1]
        assert batch["status"] == "partial"
        assert batch["targets"][0]["error"] == "result_capacity_exceeded"
        assert "rows" not in batch["targets"][0]
        assert batch["targets"][-1]["rows"] == [{"date": "2026-07-01"}]
        assert len(json.dumps(batch, ensure_ascii=False)) <= 12000


async def test_escaped_events_refuse_context_overflow_but_keep_small_target(tmp_path):
    model = QueryModel([("store_data_catalog", {}), query([
        {"id": "events", "domain": "daily_ledger", "fields": ["date", "activity"],
         "range": {"all_history": True}},
        {"id": "date", "domain": "daily_ledger", "fields": ["date"],
         "range": {"all_history": True}, "top_n": 1},
    ]), "完整事件超过本轮容量；日期目标已完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        for day in range(1, 4):
            saved = await client.put(f"/api/ledger/1/2026-07-{day:02}", json={
                "expected_identity": None, "expected_revision": None, "expected_config_revision": 1,
                "is_open": "营业", "daily_revenue": day, "activity": "\\" * 1700})
            assert saved.status_code == 201
        run = await ask(client)
        assert run["status"] == "completed", run
        batch = model.results[-1]
        assert batch["status"] == "partial", batch
        assert batch["targets"][0]["error"] == "context_capacity"
        assert "rows" not in batch["targets"][0]
        assert batch["targets"][1]["rows"] == [{"date": "2026-07-01"}]
        events = (await client.get(f"/api/agent/1/runs/{run['id']}/events")).text
        assert '"status": "partial"' in events
        assert "context_budget" not in events
