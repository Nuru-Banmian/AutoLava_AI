"""Issue #261: authenticated chat drives the real calculator, never private helpers."""

import json

import pytest

from tests.api.test_agent_chat import chat_app
from tests.api.test_agent_tools import ToolModel, ask


async def test_decimal_calculation_is_exact_and_counted_in_chat(tmp_path):
    model = ToolModel([("calculate", {"expression": "0.1+0.2"}), "结果为0.3。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "计算0.1+0.2")
        assert run["status"] == "completed", run
        assert run["calls"] == 3  # plan + tool request + answer
        assert model.results == [{"result": "0.3", "exact": True}]
        advertised = next(t["function"] for t in model.calls[0][1]
                          if t["function"]["name"] == "calculate")
        assert set(advertised["parameters"]["properties"]) == {"expression"}
        assert advertised["parameters"]["additionalProperties"] is False
        events = await client.get(f"/api/agent/1/runs/{run['id']}/events")
        tools = [json.loads(block.split("data: ", 1)[1])
                 for block in events.text.split("\n\n") if "event: tool\n" in block]
        assert tools == [{"name": "calculate", "status": "completed"}]
        history = (await client.get("/api/agent/1/conversation")).json()
        assert history["messages"][-1]["content"].endswith("结果为0.3。")


@pytest.mark.parametrize("expression,result,exact", [
    (" - (2 + 3.5) * +4 / 2 ", "-11.0", True),
    ("2+3*4", "14", True),
    (".5 + 1.25 - 2.", "-0.25", True),
    ("1/8", "0.125", True),
    ("1/3", "0." + "3" * 50, False),
    ("(1/3)*0", "0." + "0" * 50, False),
    ("9" * 50, "9" * 50, True),
    ("(" * 16 + "1" + ")" * 16, "1", True),
    ("1" + "+0" * 64, "1", True),
    ("0" * 511 + "1", "1", True),
])
async def test_calculation_grammar_precision_and_inclusive_limits(tmp_path, expression, result, exact):
    model = ToolModel([("calculate", {"expression": expression}), "计算完成。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client, "请计算给出的表达式"))["status"] == "completed"
        observed = model.results[-1]
        assert observed["result"] == result
        assert observed["exact"] is exact
        if not exact:
            assert "有限十进制" in observed["notice"]


@pytest.mark.parametrize("expression,error", [
    ("1/0", "division_by_zero"), ("0/0", "division_by_zero"),
    ("", "invalid_expression"), ("1 2", "invalid_expression"),
    ("(1+2", "invalid_expression"), ("1+", "invalid_expression"),
    ("2**3", "invalid_expression"), ("5%2", "invalid_expression"),
    ("5//2", "invalid_expression"), ("1e2", "invalid_expression"),
    ("abs(-1)", "invalid_expression"), ("(1).__class__", "invalid_expression"),
    ("[1][0]", "invalid_expression"), ("__import__('os').system('whoami')", "invalid_expression"),
    ("NaN", "invalid_expression"), ("Infinity", "invalid_expression"),
    ("1" * 513, "expression_capacity"),
    ("9" * 51, "literal_capacity"),
    ("1" + "+0" * 65, "operation_capacity"),
    ("-" * 65 + "1", "operation_capacity"),
    ("(" * 17 + "1" + ")" * 17, "nesting_capacity"),
    ("*".join(["1" + "0" * 49] * 21), "expression_capacity"),
])
async def test_calculation_fails_structurally_without_false_success(tmp_path, expression, error):
    model = ToolModel([("calculate", {"expression": expression}), "计算失败，未得到数值。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        run = await ask(client, "计算表达式")
        assert run["status"] == "completed", run
        result = model.results[-1]
        assert result["error"] == error
        assert result["message"]
        assert "result" not in result and "exact" not in result
        events = await client.get(f"/api/agent/1/runs/{run['id']}/events")
        progress = next(json.loads(block.split("data: ", 1)[1])
                        for block in events.text.split("\n\n") if "event: tool\n" in block)
        assert progress == {"name": "calculate", "status": "denied",
                            "error_code": error, "message": result["message"]}


@pytest.mark.parametrize("extra", [
    {"precision": 2}, {"rounding": "half_up"}, {"store_id": 2},
    {"user_id": 2}, {"sql": "select 1"}, {"script": "print(1)"},
])
async def test_model_cannot_add_calculation_options_or_scope(tmp_path, extra):
    model = ToolModel([("calculate", {"expression": "1+1", **extra}), "请求被拒绝。"])
    async with chat_app(tmp_path, model) as (client, _, _):
        assert (await ask(client))["status"] == "completed"
        assert model.results[-1]["error"] == "invalid_tool_arguments"
