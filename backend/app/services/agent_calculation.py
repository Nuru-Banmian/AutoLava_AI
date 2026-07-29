from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any


class CalculationValidationError(ValueError):
    pass


def _field_value(result: dict[str, Any], path: str) -> Decimal:
    current: Any = result
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise CalculationValidationError("引用的结果字段不存在")
        current = current[part]
    if isinstance(current, bool) or current is None:
        raise CalculationValidationError("引用的结果字段不是数值")
    try:
        return Decimal(str(current))
    except InvalidOperation as exc:
        raise CalculationValidationError("引用的结果字段不是数值") from exc


def _operand(
    value: dict[str, Any],
    *,
    results: dict[str, dict[str, Any]],
    steps: dict[str, Decimal],
) -> Decimal:
    if set(value) >= {"result_id", "field"}:
        result_id = value["result_id"]
        if result_id not in results:
            raise CalculationValidationError("本轮结果编号不存在")
        return _field_value(results[result_id], str(value["field"]))
    if "step" in value:
        try:
            return steps[str(value["step"])]
        except KeyError as exc:
            raise CalculationValidationError("引用的计算步骤不存在") from exc
    if "literal" in value:
        if not str(value.get("source", "")).strip():
            raise CalculationValidationError("字面量必须标明来源")
        try:
            return Decimal(str(value["literal"]))
        except InvalidOperation as exc:
            raise CalculationValidationError("字面量不是有效数值") from exc
    raise CalculationValidationError("计算操作数无效")


def calculate(
    plan: list[dict[str, Any]],
    *,
    results: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if not plan or len(plan) > 20:
        raise CalculationValidationError("计算步骤数量无效")
    values: dict[str, Decimal] = {}
    unavailable: dict[str, str] = {}
    for item in plan:
        name = str(item.get("name", "")).strip()
        operation = item.get("operation")
        if not name or name in values or name in unavailable:
            raise CalculationValidationError("计算步骤名称无效")
        left = _operand(item.get("left", {}), results=results, steps=values)
        right = _operand(item.get("right", {}), results=results, steps=values)
        if operation == "add":
            value = left + right
        elif operation == "subtract":
            value = left - right
        elif operation == "multiply":
            value = left * right
        elif operation == "divide":
            if right == 0:
                unavailable[name] = "除数为零，无法计算"
                continue
            value = left / right
        else:
            raise CalculationValidationError("不支持的计算操作")
        if "scale" in item:
            scale = item["scale"]
            if not isinstance(scale, int) or not 0 <= scale <= 6:
                raise CalculationValidationError("舍入位数无效")
            quantum = Decimal(1).scaleb(-scale)
            rounding = (
                ROUND_DOWN
                if item.get("rounding") == "truncate"
                else ROUND_HALF_UP
            )
            value = value.quantize(quantum, rounding=rounding)
        values[name] = value
    return {
        "status": "completed",
        "values": {name: format(value, "f") for name, value in values.items()},
        "unavailable": unavailable,
    }
