"""Decimal arithmetic with a closed grammar; expressions are never Python code."""

import re
import json
from decimal import Context, Decimal, DecimalException, Inexact, Subnormal, localcontext

from pydantic import BaseModel, ConfigDict


class CalculateInput(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    expression: str


class CalculationError(Exception):
    def __init__(self, code, message):
        self.code, self.message = code, message


class Expression:
    def __init__(self, source):
        if len(source) > 512:
            raise CalculationError("expression_capacity", "表达式最多512字符。")
        self.tokens = []
        operations = depth = 0
        position = 0
        while position < len(source):
            if source[position].isspace():
                position += 1
                continue
            match = re.match(r"(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)|[()+*/-]", source[position:])
            if match is None:
                raise CalculationError("invalid_expression", "仅支持十进制数、四则运算和括号。")
            token = match.group()
            if token in ("+", "-", "*", "/"):
                operations += 1
                if operations > 64:
                    raise CalculationError("operation_capacity", "表达式最多64次运算（含正负号）。")
            elif token == "(":
                depth += 1
                if depth > 16:
                    raise CalculationError("nesting_capacity", "括号最多嵌套16层。")
            elif token == ")":
                depth -= 1
                if depth < 0:
                    raise CalculationError("invalid_expression", "括号不匹配。")
            elif len(token.replace(".", "").lstrip("0")) > 50:
                raise CalculationError("literal_capacity", "每个十进制字面量最多50个有效数字。")
            self.tokens.append(token)
            position += len(match.group())
        self.position = 0

    def peek(self):
        return self.tokens[self.position] if self.position < len(self.tokens) else None

    def take(self):
        token = self.peek()
        self.position += 1
        return token

    def parse(self):
        value = self.sum()
        if self.peek() is not None:
            raise CalculationError("invalid_expression", "表达式语法无效。")
        return value

    def sum(self):
        value = self.product()
        while self.peek() in ("+", "-"):
            operator = self.take()
            right = self.product()
            value = value + right if operator == "+" else value - right
        return value

    def product(self):
        value = self.factor()
        while self.peek() in ("*", "/"):
            operator = self.take()
            right = self.factor()
            if operator == "/" and not right:
                raise CalculationError("division_by_zero", "除数不能为零。")
            value = value * right if operator == "*" else value / right
        return value

    def factor(self):
        token = self.take()
        if token in ("+", "-"):
            value = self.factor()
            return +value if token == "+" else -value
        if token == "(":
            value = self.sum()
            if self.take() != ")":
                raise CalculationError("invalid_expression", "括号不匹配。")
            return value
        if token is None or token in (")", "*", "/"):
            raise CalculationError("invalid_expression", "表达式语法无效。")
        return Decimal(token)


async def calculate(session, context, arguments: CalculateInput):
    try:
        with localcontext(Context(prec=50, Emin=-1000, Emax=1000)) as decimal_context:
            decimal_context.traps[Subnormal] = True
            value = Expression(arguments.expression).parse()
            if not value.is_finite() or (value and not -1000 <= value.adjusted() <= 1000):
                raise CalculationError("calculation_overflow", "结果指数必须介于-1000与1000。")
            exact = not decimal_context.flags[Inexact]
            text = format(value, "f")
            if len(text) > 2048:
                raise CalculationError("result_capacity", "结果文本最多2048字符。")
            result = {"result": text, "exact": exact}
            if not exact:
                result["notice"] = "结果为50位有效数字下的有限十进制表示，并非无限精确值。"
            if len(json.dumps(result, ensure_ascii=False)) > context.remaining_result_chars:
                return {"error": "context_capacity", "message": "本轮剩余上下文不足以返回完整计算结果。"}
            return result
    except CalculationError as exc:
        return {"error": exc.code, "message": exc.message}
    except DecimalException:
        return {"error": "calculation_overflow", "message": "计算超出支持的十进制范围。"}
