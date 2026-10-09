"""Business outcomes over HTTP/SSE, no ORM fixtures or production logic reimplementation."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import json
from uuid import uuid4

import httpx

from acceptance.server import PASSWORD


def request(client, method, path, status=200, **kwargs):
    response = client.request(method, path, **kwargs)
    assert response.status_code == status, response.text
    return response.json() if response.content else None


def store(owner):
    return request(owner, "POST", "admin/stores", 201, json={
        "name": "验收门店-" + uuid4().hex[:8], "address": "Rome",
        "latitude": "41.9", "longitude": "12.5", "timezone": "Europe/Rome",
    })["id"]


def user(owner, store_ids, role="user"):
    username = "acceptance-" + uuid4().hex[:10]
    created = request(owner, "POST", "admin/users", 201, json={
        "username": username, "password": PASSWORD, "role": role, "store_ids": store_ids,
    })
    return created["id"], username


@contextmanager
def login(base_url, username):
    with httpx.Client(base_url=base_url + "/", timeout=15, trust_env=False) as client:
        request(client, "POST", "auth/login", json={"username": username, "password": PASSWORD})
        yield client


def version(record):
    return {"expected_identity": record.get("identity"),
            "expected_revision": record.get("revision"),
            "expected_config_revision": record["config_revision"]}


def save(client, store_id, date, amount=None, state="营业"):
    path = f"ledger/{store_id}/{date}"
    response = client.get(path)
    assert response.status_code in (200, 404), response.text
    if response.status_code == 404:
        config = request(client, "GET", path + "/form-config")
        snapshot = {"config_revision": config["config_revision"]}
    else:
        snapshot = response.json()
    return request(client, "PUT", path, 201 if not snapshot.get("identity") else 200,
                   json={**version(snapshot), "is_open": state, "daily_revenue": amount})


def charts(client, store_id, start="2025-01-01", end="2025-01-04"):
    return request(client, "GET", f"charts/{store_id}", params={"start": start, "end": end})


def test_login_store_permissions_and_revocation(owner, base_url):
    first, private = store(owner), store(owner)
    user_id, username = user(owner, [first])
    save(owner, private, "2025-01-01", 999)
    with httpx.Client(base_url=base_url + "/", trust_env=False) as anonymous:
        request(anonymous, "GET", f"ledger/{first}/2025-01-01", 401)
        request(anonymous, "POST", "auth/login", 401,
                json={"username": username, "password": "incorrect-password"})
    with login(base_url, username) as member:
        assert [s["id"] for s in request(member, "GET", "stores/accessible")] == [first]
        saved = save(member, first, "2025-01-01", 42)
        request(member, "GET", f"ledger/{private}/2025-01-01", 404)
        request(member, "GET", f"charts/{private}?start=2025-01-01&end=2025-01-04", 404)
        request(member, "GET", "admin/users", 403)
        request(member, "GET", f"agent/{first}/conversation", 403)
        request(owner, "PATCH", f"admin/users/{user_id}", json={"store_ids": []})
        request(member, "PUT", f"ledger/{first}/2025-01-01", 401,
                json={**version(saved), "is_open": "营业", "daily_revenue": 700})
        request(owner, "PATCH", f"admin/users/{user_id}", json={"is_active": False})
        request(member, "GET", "auth/me", 401)
    assert request(owner, "GET", f"ledger/{first}/2025-01-01")["daily_revenue"] == 42


def test_competing_ledger_writers_and_deleted_identity(owner, base_url):
    store_id = store(owner)
    _, username = user(owner, [store_id])
    initial = save(owner, store_id, "2025-01-01", 10)
    path = f"ledger/{store_id}/2025-01-01"
    with login(base_url, username) as second:
        def write(pair):
            client, amount = pair
            return client.put(path, json={**version(initial), "is_open": "营业",
                                          "daily_revenue": amount})
        with ThreadPoolExecutor(max_workers=2) as pool:
            responses = list(pool.map(write, [(owner, 81), (second, 93)]))
    assert sorted(r.status_code for r in responses) == [200, 409]
    winner = next(r.json() for r in responses if r.status_code == 200)
    persisted = request(owner, "GET", path)
    assert persisted["daily_revenue"] == winner["daily_revenue"]
    assert persisted["revision"] == initial["revision"] + 1
    request(owner, "DELETE", path, 204, json={
        "expected_identity": persisted["identity"], "expected_revision": persisted["revision"],
    })
    replacement = save(owner, store_id, "2025-01-01", 17)
    assert replacement["identity"] != initial["identity"]
    request(owner, "PUT", path, 409,
            json={**version(persisted), "is_open": "营业", "daily_revenue": 888})
    assert request(owner, "GET", path)["daily_revenue"] == 17


def test_unreported_zero_and_missing_remain_distinct(owner):
    store_id = store(owner)
    save(owner, store_id, "2025-01-01", None, "未统计")
    save(owner, store_id, "2025-01-02", 0)
    save(owner, store_id, "2025-01-03", 80)
    result = charts(owner, store_id)
    assert [(row["is_open"], row["revenue"]) for row in result["daily"]] == [
        ("未统计", None), ("营业", 0), ("营业", 80),
    ]
    assert result["kpis"]["open_days"] == 2
    assert result["kpis"]["average_revenue"] == 40
    assert result["period_coverage"]["unreported_days"] == 1
    assert result["period_coverage"]["missing_record_days"] == 1
    assert result["income_summary"]["total_income"] == 80


def test_income_configuration_fences_stale_forms_and_excludes_other_data(owner):
    store_id = store(owner)
    path = f"ledger/{store_id}/2025-01-01"
    previous = save(owner, store_id, "2025-01-01", 10)
    config_path = f"admin/stores/{store_id}/income-config"
    config = request(owner, "GET", config_path)
    published = request(owner, "PUT", config_path, json={
        "expected_revision": config["revision"], "enabled": True, "items": [
            {"name": "服务收入", "include_in_total": True, "sort_order": 0},
            {"name": "其他数据", "include_in_total": False, "sort_order": 1},
        ],
    })
    request(owner, "PUT", path, 428, json={"is_open": "营业", "daily_revenue": 55})
    request(owner, "PUT", path, 409,
            json={**version(previous), "is_open": "营业", "daily_revenue": 55})
    assert request(owner, "GET", path)["daily_revenue"] == 10
    values = {"服务收入": 60, "其他数据": 500}
    path = f"ledger/{store_id}/2025-01-02"
    request(owner, "PUT", path, 201, json={
        "expected_identity": None, "expected_revision": None,
        "expected_config_revision": published["revision"], "is_open": "营业",
        "items": [{"category_id": item["id"], "amount": values[item["name"]]}
                  for item in published["items"]],
    })
    assert request(owner, "GET", path)["daily_revenue"] == 60
    result = charts(owner, store_id)
    assert result["income_summary"]["total_income"] == 70
    assert [(item["category_name"], item["amount"]) for item in result["excluded_categories"]] == [
        ("其他数据", 500),
    ]


def test_settlement_confirmation_month_and_reversal(owner):
    store_id, other = store(owner), store(owner)
    request(owner, "PATCH", f"admin/stores/{store_id}",
            json={"company_settlement_enabled": True})
    request(owner, "PATCH", f"admin/stores/{other}",
            json={"company_settlement_enabled": True})
    save(owner, store_id, "2025-01-02", 80)
    company = request(owner, "POST", f"settlements/{store_id}/companies", 201,
                      json={"name": "验收公司"})
    request(owner, "POST", f"settlements/{other}/records", 404,
            json={"company_id": company["id"], "opening_month": "2025-01", "amount": 120})
    record = request(owner, "POST", f"settlements/{store_id}/records", 201,
                     json={"company_id": company["id"], "opening_month": "2025-01",
                           "amount": 120})
    month_path = f"settlements/{store_id}/months/2025-01"
    pending = request(owner, "GET", month_path)
    assert (pending["pending_amount"], pending["monthly_total"]) == (120, 80)
    path = f"settlements/{store_id}/records/{record['id']}"
    confirmed = request(owner, "POST", path + "/confirm", json={"revision": record["revision"]})
    request(owner, "POST", path + "/confirm", 409, json={"revision": record["revision"]})
    request(owner, "PATCH", path, 409, json={"revision": confirmed["revision"], "amount": 200})
    assert request(owner, "GET", month_path)["monthly_total"] == 200
    assert charts(owner, store_id, "2025-01-02", "2025-01-02")["income_summary"] == {
        "daily_ledger_revenue": 80, "confirmed_settlement_income": 120,
        "total_income": 200, "includes_settlement_income": True,
    }
    assert charts(owner, store_id, "2025-02-01", "2025-02-02")["income_summary"]["total_income"] == 0
    request(owner, "PATCH", f"admin/stores/{store_id}",
            json={"company_settlement_enabled": False})
    request(owner, "GET", month_path, 403)
    assert charts(owner, store_id)["income_summary"]["confirmed_settlement_income"] == 120
    request(owner, "PATCH", f"admin/stores/{store_id}",
            json={"company_settlement_enabled": True})
    request(owner, "POST", path + "/revoke-confirmation", json={"revision": confirmed["revision"]})
    assert request(owner, "GET", month_path)["monthly_total"] == 80
    assert charts(owner, store_id)["income_summary"]["confirmed_settlement_income"] == 0


def events(client, path, until=None):
    # Stream while the real run executes; reconnect cursor is checked separately.
    captured = []
    with client.stream("GET", path) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        block = {}
        for line in response.iter_lines():
            if not line:
                if "data" in block:
                    captured.append((int(block["id"]), block["event"], json.loads(block["data"])))
                    if until and until(captured[-1]):
                        break
                block = {}
            elif not line.startswith(":"):
                key, value = line.split(":", 1)
                block[key] = value.strip()
    return captured


def test_agent_receipts_charts_restore_and_reset_scope(owner, base_url):
    store_id, other = store(owner), store(owner)
    _, username = user(owner, [store_id, other], "admin")
    save(owner, store_id, "2025-01-01", None, "未统计")
    save(owner, store_id, "2025-01-02", 0)
    save(owner, store_id, "2025-01-03", 81)
    save(owner, other, "2025-01-03", 999)
    base = f"agent/{store_id}"
    submitted = request(owner, "POST", base + "/messages", 202, json={
        "content": "查询2025年1月1至4日营业额并画图，另算0.1+0.2", "generation": 0,
        "request_id": uuid4().hex,
    })
    run_path = base + f"/runs/{submitted['id']}"
    captured = events(owner, run_path + "/events")
    assert captured[-1][1] == "completed", captured
    assert [payload["name"] for _, kind, payload in captured if kind == "tool"] == [
        "read_skill", "store_data_catalog", "store_query", "calculate", "store_chart",
    ]
    assert all(payload["status"] == "completed" for _, kind, payload in captured if kind == "tool")
    replay = events(owner, run_path + f"/events?after={captured[-2][0]}")
    assert replay == captured[-1:]
    complete = request(owner, "GET", run_path)
    receipt = json.loads(complete["output"].split("验收结果：", 1)[1])
    assert receipt["calculation"] == {"result": "0.3", "exact": True}
    assert "999" not in complete["output"]
    conversation = request(owner, "GET", base + "/conversation")
    assistant = conversation["messages"][-1]
    assert assistant["role"] == "assistant"
    assert assistant["content"] == complete["output"]
    assert len(assistant["charts"]) == 1
    chart_path = base + f"/messages/{assistant['id']}/charts/{assistant['charts'][0]['chart_id']}"
    snapshot = request(owner, "GET", chart_path)
    assert [point["values"]["total_revenue"]["exact"] for point in snapshot["payload"]["points"]] == [
        None, "0", "81", None,
    ]
    # A fresh login observes durable chat/chart state, including after live ledger edits.
    save(owner, store_id, "2025-01-03", 150)
    with login(base_url, "ci-owner") as reopened, login(base_url, username) as other_admin:
        assert request(reopened, "GET", chart_path) == snapshot
        assert request(reopened, "GET", base + "/conversation")["messages"] == conversation["messages"]
        assert request(other_admin, "GET", base + "/conversation")["messages"] == []
        request(other_admin, "GET", chart_path, 404)
        request(owner, "GET", f"agent/{other}/runs/{submitted['id']}", 404)
        # Vary one scope dimension at a time: user-only/store-only resets must fail.
        controls = []
        for client, scope in ((other_admin, base), (owner, f"agent/{other}")):
            second = request(client, "POST", scope + "/messages", 202, json={
                "content": "查询并画图", "generation": 0, "request_id": uuid4().hex,
            })
            assert events(client, scope + f"/runs/{second['id']}/events")[-1][1] == "completed"
            history = request(client, "GET", scope + "/conversation")
            message = history["messages"][-1]
            assert len(history["messages"]) == 2 and len(message["charts"]) == 1
            saved_path = scope + f"/messages/{message['id']}/charts/{message['charts'][0]['chart_id']}"
            controls.append((client, scope, history, saved_path, request(client, "GET", saved_path)))
        reset = request(owner, "POST", base + "/conversation/reset", json={"generation": 0})
        assert reset["generation"] == 1 and reset["messages"] == []
        request(owner, "GET", chart_path, 404)
        request(owner, "POST", base + "/messages", 409, json={
            "content": "过期页面提交", "generation": 0, "request_id": uuid4().hex,
        })
        for client, scope, history, saved_path, saved in controls:
            assert request(client, "GET", scope + "/conversation") == history
            assert request(client, "GET", saved_path) == saved


def test_agent_failure_and_reset_during_model_wait(owner):
    store_id = store(owner)
    save(owner, store_id, "2025-01-03", 81)
    base = f"agent/{store_id}"
    failed = request(owner, "POST", base + "/messages", 202, json={
        "content": "模拟模型失败", "generation": 0, "request_id": uuid4().hex,
    })
    captured = events(owner, base + f"/runs/{failed['id']}/events")
    assert captured[-1][1:] == ("failed", {"error_code": "model_unavailable"})
    assert request(owner, "GET", base + f"/runs/{failed['id']}")["status"] == "failed"
    history = request(owner, "GET", base + "/conversation")
    assert [message["role"] for message in history["messages"]] == ["user"]
    reset = request(owner, "POST", base + "/conversation/reset", json={"generation": 0})
    payload = {"content": "查询并画图后等待重置", "generation": reset["generation"],
               "request_id": uuid4().hex}
    running = request(owner, "POST", base + "/messages", 202, json=payload)
    replay = request(owner, "POST", base + "/messages", 202, json=payload)
    assert replay["id"] == running["id"]
    stream_path = base + f"/runs/{running['id']}/events"
    captured = events(owner, stream_path,
                      until=lambda event: event[1] == "delta" and
                      event[2]["text"] == "等待重置信号")
    assert captured[-1][2]["text"] == "等待重置信号"
    assert request(owner, "GET", base + f"/runs/{running['id']}")["status"] == "running"
    request(owner, "POST", base + "/conversation/reset", json={"generation": reset["generation"]})
    fenced = request(owner, "GET", base + f"/runs/{running['id']}")
    assert fenced["status"] == "failed" and fenced["error_code"] == "reset"
    assert fenced["output"] == ""
    conversation = request(owner, "GET", base + "/conversation")
    assert conversation["messages"] == [] and conversation["run"] is None
