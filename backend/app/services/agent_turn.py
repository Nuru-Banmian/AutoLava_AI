import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
import json
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import sqlite_short_write
from app.models.agent import AgentInvestigationCard, AgentMessage, AgentTurn
from app.models.identity import Store
from app.services.agent_calculation import calculate
from app.services.agent_conversation import (
    AGENT_SCOPE_EXPLANATION,
    bounded_model_context,
    capability_gap_answer,
    capability_gap_guidance,
    capability_gap_terms,
    conversation_messages,
    fit_model_context,
    get_or_create_conversation,
    is_business_scope_question,
    interpret_time_scope,
    relevant_investigation_context,
    refresh_context_summary,
    trusted_store_context,
)
from app.services.agent_data_tools import (
    AgentDataToolRegistry,
    DataToolContext,
)
from app.services.agent_model import (
    AgentModelAdapter,
    ModelMessage,
    ModelResponse,
    ModelTool,
    ModelToolCall,
)
from app.services.agent_skills import SkillCatalog

TURN_FAILED_MESSAGE = "Agent 本轮处理失败，请稍后重试"
TURN_INTERRUPTED_MESSAGE = "后端进程已重新启动，本轮未自动继续"
_END = object()
logger = logging.getLogger(__name__)

_REVENUE_FIELDS = frozenset(
    {
        "confirmed_settlement_income",
        "ledger_revenue",
        "monthly_total_income",
        "total_income",
    }
)
_PENDING_FIELD = "current_pending_receivables"
_ALLOWED_LITERAL_SOURCES = frozenset({"user", "formula_constant"})
_FORMULA_CONSTANTS = frozenset({"100"})
_PENDING_EXCLUSION_PHRASES = (
    "不计入营业额",
    "不计入月度总收入",
    "不属于营业额",
    "不属于收入",
)
_CAPABILITY_FIELD_PRESENTATION = {
    "data.ledger_revenue": ("台账营业额", "欧元"),
    "data.operating_days": ("经营日", "天"),
    "data.operating_day_average_ledger_revenue": (
        "经营日均台账营业额",
        "欧元",
    ),
    "data.wash_count": ("洗车数量", "辆"),
    "data.average_revenue_per_wash": ("平均每车收入", "欧元"),
    "data.classified_ledger_revenue": ("分类记账营业额", "欧元"),
    "data.other_data_total": ("其他数据合计", "欧元"),
    "data.confirmed_settlement_income": ("已确认公司结算收入", "欧元"),
    "data.current_pending_receivables": ("当前待到账应收款", "欧元"),
    "coverage.range_start": ("数据覆盖开始日期", ""),
    "coverage.range_end": ("数据覆盖结束日期", ""),
    "coverage.matching_records": ("匹配记录", "条"),
    "coverage.operating_days": ("数据覆盖经营日", "天"),
    "coverage.truncated": ("数据是否截断", ""),
}
_CAPABILITY_LIST_PRESENTATION = {
    "data.points": "台账营业额趋势",
    "data.groups": "分组结果",
    "data.income_categories": "收入分类",
    "data.other_data": "其他数据",
    "data.records": "明细",
    "data.companies": "结算公司目录",
}
_CAPABILITY_ROW_FIELD_PRESENTATION = {
    "period": ("期间", ""),
    "date": ("日期", ""),
    "label": ("分组", ""),
    "category_name": ("分类名称", ""),
    "company_name": ("结算公司", ""),
    "opening_month": ("开票月份", ""),
    "status": ("状态", ""),
    "operating_status": ("营业状态", ""),
    "recorded_weather": ("记录天气", ""),
    "weather": ("记录天气", ""),
    "event": ("事件", ""),
    "events": ("事件", ""),
    "ledger_revenue": ("台账营业额", "欧元"),
    "daily_revenue": ("台账营业额", "欧元"),
    "amount": ("金额", "欧元"),
    "confirmed_settlement_income": ("已确认公司结算收入", "欧元"),
    "current_pending_receivables": ("当前待到账应收款", "欧元"),
    "operating_days": ("经营日", "天"),
    "operating_day_average_ledger_revenue": (
        "经营日均台账营业额",
        "欧元",
    ),
    "wash_count": ("洗车数量", "辆"),
    "proportion": ("占比", "%"),
    "include_in_ledger_revenue": ("是否计入营业额", ""),
}
_ANSWER_FIELD_MARKERS = (
    (
        ("经营日均台账营业额",),
        frozenset({"operating_day_average_ledger_revenue"}),
    ),
    (("平均每车收入",), frozenset({"average_revenue_per_wash"})),
    (
        ("已确认公司结算收入",),
        frozenset({"confirmed_settlement_income"}),
    ),
    (
        ("当前待到账应收款", "待到账应收款"),
        frozenset({"current_pending_receivables"}),
    ),
    (
        ("分类记账营业额",),
        frozenset({"classified_ledger_revenue"}),
    ),
    (
        ("台账营业额", "营业额"),
        frozenset(
            {
                "ledger_revenue",
                "daily_revenue",
                "classified_ledger_revenue",
            }
        ),
    ),
    (
        ("洗车数量",),
        frozenset({"wash_count", "missing_wash_count_days"}),
    ),
    (
        ("经营日",),
        frozenset({"operating_days", "missing_wash_count_days"}),
    ),
    (("其他数据",), frozenset({"other_data_total"})),
    (("占比", "比例"), frozenset({"proportion"})),
    (
        ("匹配记录", "返回记录", "记录数"),
        frozenset({"matching_records", "returned_records"}),
    ),
    (("匹配公司", "公司数量"), frozenset({"matching_companies"})),
    (("金额",), frozenset({"amount"})),
)
_ANSWER_BUSINESS_NUMBER_CUES = (
    "欧元",
    "金额",
    "收入",
    "营业额",
    "应收",
    "经营日",
    "洗车",
    "占比",
    "比例",
    "平均",
    "合计",
    "总计",
    "增长",
    "下降",
    "变化",
    "差额",
    "记录数",
    "匹配记录",
    "公司数量",
    "%",
)

SessionFactory = Callable[[], AbstractAsyncContextManager[AsyncSession]]
AdapterFactory = Callable[[], AgentModelAdapter]
TurnEvent = dict[str, Any]


class ActiveAgentTurnError(RuntimeError):
    pass


class AgentTurnStartTimeoutError(RuntimeError):
    pass


def _calculation_operand_kinds(
    operand: object,
    step_kinds: dict[str, frozenset[str]],
) -> frozenset[str]:
    if not isinstance(operand, dict):
        return frozenset()
    field = str(operand.get("field", ""))
    field_name = field.rsplit(".", 1)[-1]
    if field_name == _PENDING_FIELD:
        return frozenset({"pending"})
    if field_name in _REVENUE_FIELDS:
        return frozenset({"revenue"})
    source = str(operand.get("source", "")).casefold()
    if any(
        marker in source
        for marker in (
            "营业额",
            "收入",
            "confirmed_settlement_income",
            "ledger_revenue",
            "total_income",
        )
    ):
        return frozenset({"revenue"})
    step = str(operand.get("step", ""))
    return step_kinds.get(step, frozenset())


def _user_supplied_numbers(content: str) -> frozenset[Decimal]:
    without_periods = re.sub(
        r"\bresult-\d+\b",
        " ",
        content,
        flags=re.IGNORECASE,
    )
    without_periods = re.sub(
        r"\d{4}\s*(?:-|年)\s*\d{1,2}\s*(?:-|月)\s*\d{1,2}\s*日?",
        " ",
        without_periods,
    )
    without_periods = re.sub(
        r"\d{4}\s*年\s*\d{1,2}\s*[-–—]\s*\d{1,2}\s*月",
        " ",
        without_periods,
    )
    without_periods = re.sub(
        r"\d{1,2}\s*月\s*\d{1,2}\s*日"
        r"(?:\s*(?:至|到|-)\s*\d{1,2}\s*日)?",
        " ",
        without_periods,
    )
    without_periods = re.sub(
        r"\d{4}\s*(?:-\s*\d{1,2}|年\s*\d{1,2}\s*月)",
        " ",
        without_periods,
    )
    without_periods = re.sub(
        r"\d{4}\s*年|(?<![\d-])\d{1,2}\s*月",
        " ",
        without_periods,
    )
    without_periods = re.sub(
        r"(?<![\d-])\d{1,2}\s*日",
        " ",
        without_periods,
    )
    without_periods = re.sub(
        r"(?:\d{4}\s*年?\s*)?(?:第?\s*[1-4一二三四]\s*季度|Q[1-4])",
        " ",
        without_periods,
        flags=re.IGNORECASE,
    )
    without_periods = re.sub(
        r"(?:最近|过去)\s*\d+\s*(?:天|周|个月|月)",
        " ",
        without_periods,
    )
    values: set[Decimal] = set()
    for matched in re.findall(
        r"(?<![A-Za-z0-9])[-+]?\d[\d,]*(?:\.\d+)?",
        without_periods,
    ):
        try:
            values.add(Decimal(matched.replace(",", "")))
        except InvalidOperation:
            continue
    return frozenset(values)


def _operand_depends_on_result(
    operand: object,
    step_dependencies: dict[str, bool],
) -> bool:
    if not isinstance(operand, dict):
        return False
    if isinstance(operand.get("result_id"), str):
        return True
    return step_dependencies.get(str(operand.get("step", "")), False)


def _validate_settlement_calculation(
    plan: object,
    *,
    user_content: str,
) -> None:
    if not isinstance(plan, list):
        return
    step_kinds: dict[str, frozenset[str]] = {}
    step_dependencies: dict[str, bool] = {}
    supplied_numbers = _user_supplied_numbers(user_content)
    for item in plan:
        if not isinstance(item, dict):
            continue
        depends_on_result = any(
            _operand_depends_on_result(
                item.get(operand_name),
                step_dependencies,
            )
            for operand_name in ("left", "right")
        )
        uses_formula_constant = False
        for operand_name in ("left", "right"):
            operand = item.get(operand_name)
            if (
                isinstance(operand, dict)
                and "literal" in operand
                and operand.get("source") not in _ALLOWED_LITERAL_SOURCES
            ):
                raise ValueError(
                    "派生计算字面量必须标记为用户输入或公式常量"
                )
            if not isinstance(operand, dict) or "literal" not in operand:
                continue
            source = operand.get("source")
            literal = str(operand.get("literal"))
            if source == "formula_constant":
                uses_formula_constant = True
                if literal not in _FORMULA_CONSTANTS:
                    raise ValueError("派生计算使用了未授权的公式常量")
            if source == "user":
                try:
                    user_value = Decimal(literal.replace(",", ""))
                except InvalidOperation as exc:
                    raise ValueError("用户数值来源无效") from exc
                if user_value not in supplied_numbers:
                    raise ValueError("派生计算字面量并非用户明确提供的数值")
        if uses_formula_constant and not depends_on_result:
            raise ValueError("公式常量必须用于依赖本轮结果的计算")
        kinds = _calculation_operand_kinds(
            item.get("left"),
            step_kinds,
        ) | _calculation_operand_kinds(
            item.get("right"),
            step_kinds,
        )
        if (
            item.get("operation") == "add"
            and {"pending", "revenue"} <= kinds
        ):
            raise ValueError("待到账应收款不能与营业额指标合并计算")
        name = str(item.get("name", "")).strip()
        if name:
            step_kinds[name] = kinds
            step_dependencies[name] = depends_on_result


def _validate_settlement_answer(
    answer: str,
    *,
    loaded_skills: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> frozenset[Decimal]:
    if "company_settlement" not in loaded_skills:
        return frozenset()
    summaries = [
        result
        for result in results.values()
        if {
            "confirmed_settlement_income",
            "current_pending_receivables",
        }
        <= set(result.get("data", {}))
    ]
    if not summaries:
        return frozenset()
    if (
        "已确认公司结算收入" not in answer
        or "当前待到账应收款" not in answer
        or not any(phrase in answer for phrase in _PENDING_EXCLUSION_PHRASES)
    ):
        raise ValueError("公司结算最终回答未分离收入与当前待到账应收款")
    risky_inclusion = re.search(
        r"(?:当前)?待到账应收款.{0,20}(?:计入|纳入|包含在|构成)"
        r".{0,15}(?:营业额|月度总收入|收入)",
        answer,
    )
    if risky_inclusion and "不" not in risky_inclusion.group(0):
        raise ValueError("公司结算最终回答错误计入待到账应收款")
    if re.search(
        r"(?:两项|二者|上述两类|合并|加总).{0,12}(?:收入|营业额)",
        answer,
    ) or re.search(
        r"(?:公司结算|已确认).{0,12}(?:和|与|加上).{0,12}"
        r"(?:应收|待到账).{0,12}(?:合计|总计|收入|营业额)",
        answer,
    ):
        raise ValueError("公司结算最终回答合并了收入与当前待到账应收款")
    for sentence in re.split(r"[。！？\n]+", answer):
        if (
            "公司结算收入" in sentence
            and re.search(
                r"(?:\d{4}\s*-\s*\d{1,2}\s*-\s*\d{1,2}"
                r"|\d{4}\s*年\s*\d{1,2}\s*月\s*\d{1,2}\s*日"
                r"|\d{1,2}\s*月\s*\d{1,2}\s*日)",
                sentence,
            )
        ):
            raise ValueError("公司结算收入不能归因到日粒度")

    claimed_monthly_totals = re.findall(
        r"月度总收入[^0-9。\n]{0,30}([0-9][0-9,.]*)\s*欧元",
        answer,
    )
    if not claimed_monthly_totals:
        return frozenset()
    permitted_totals: set[Decimal] = set()
    performance_results = [
        result
        for result in results.values()
        if "ledger_revenue" in result.get("data", {})
    ]
    for settlement in summaries:
        for performance in performance_results:
            settlement_start = str(
                settlement.get("coverage", {}).get("range_start", "")
            )
            settlement_end = str(
                settlement.get("coverage", {}).get("range_end", "")
            )
            performance_start = str(
                performance.get("coverage", {}).get("range_start", "")
            )
            performance_end = str(
                performance.get("coverage", {}).get("range_end", "")
            )
            if (
                settlement_start[:7] != performance_start[:7]
                or settlement_end[:7] != performance_end[:7]
            ):
                continue
            try:
                permitted_totals.add(
                    Decimal(
                        performance["data"]["ledger_revenue"]
                    )
                    + Decimal(
                        settlement["data"][
                            "confirmed_settlement_income"
                        ]
                    )
                )
            except (InvalidOperation, KeyError, TypeError):
                continue
    try:
        parsed_claims = {
            Decimal(value.replace(",", ""))
            for value in claimed_monthly_totals
        }
    except InvalidOperation as exc:
        raise ValueError("月度总收入金额格式无效") from exc
    if not parsed_claims <= permitted_totals:
        raise ValueError("月度总收入必须由同期间台账营业额和已确认公司结算收入组成")
    return frozenset(parsed_claims)


def _result_number_fields(
    value: object,
    *,
    path: tuple[str, ...] = (),
) -> dict[Decimal, set[tuple[str, ...]]]:
    if isinstance(value, dict):
        fields: dict[Decimal, set[tuple[str, ...]]] = {}
        for key, item in value.items():
            for number, number_paths in _result_number_fields(
                item,
                path=(*path, str(key)),
            ).items():
                fields.setdefault(number, set()).update(number_paths)
        return fields
    if isinstance(value, (list, tuple)):
        fields = {}
        for item in value:
            for number, number_paths in _result_number_fields(
                item,
                path=path,
            ).items():
                fields.setdefault(number, set()).update(number_paths)
        return fields
    if isinstance(value, bool) or value is None:
        return {}
    try:
        return {Decimal(str(value).replace(",", "")): {path}}
    except InvalidOperation:
        return {}


def _answer_number_claims(answer: str) -> list[tuple[Decimal, str]]:
    claims: list[tuple[Decimal, str]] = []
    for clause in re.split(r"[，,；;。！？\n]+", answer):
        claims.extend(
            (number, clause)
            for number in _user_supplied_numbers(clause)
        )
    return claims


def _validate_business_answer(
    answer: str,
    *,
    user_content: str,
    loaded_skills: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> None:
    permitted_settlement_totals = _validate_settlement_answer(
        answer,
        loaded_skills=loaded_skills,
        results=results,
    )
    result_fields = _result_number_fields(results)
    generic_numbers = set(_user_supplied_numbers(user_content))
    generic_numbers.update(permitted_settlement_totals)
    generic_numbers.update(
        number
        for number, paths in result_fields.items()
        if any("values" in path for path in paths)
    )
    for number, clause in _answer_number_claims(answer):
        if not any(cue in clause for cue in _ANSWER_BUSINESS_NUMBER_CUES):
            continue
        if number in generic_numbers:
            continue
        permitted_fields = set()
        for markers, fields in _ANSWER_FIELD_MARKERS:
            if any(marker in clause for marker in markers):
                permitted_fields.update(fields)
        if any(
            path
            and path[-1] in permitted_fields
            for path in result_fields.get(number, ())
        ):
            continue
        raise ValueError("最终回答包含未绑定到本轮可信证据字段的业务数值")


def _submitted_capability_answer(
    arguments: object,
    *,
    results: dict[str, dict[str, Any]],
    missing_capabilities: tuple[str, ...],
) -> str:
    if not isinstance(arguments, dict) or set(arguments) != {"evidence"}:
        raise ValueError("能力缺口回答提交参数无效")
    evidence = arguments["evidence"]
    if not isinstance(evidence, list) or len(evidence) > 20:
        raise ValueError("能力缺口回答证据无效")
    accepted: list[str] = []
    submitted_fields: set[str] = set()
    settlement_fields = {
        "data.confirmed_settlement_income",
        "data.current_pending_receivables",
    }
    for item in evidence:
        if (
            not isinstance(item, dict)
            or set(item) != {"result_id", "fields"}
        ):
            raise ValueError("能力缺口回答证据无效")
        result_id = item["result_id"]
        fields = item["fields"]
        if (
            not isinstance(result_id, str)
            or result_id not in results
            or not isinstance(fields, list)
            or not fields
            or len(fields) > 20
        ):
            raise ValueError("能力缺口回答引用了无效的本轮结果编号")
        fields = list(fields)
        result_data = results[result_id].get("data")
        if (
            isinstance(result_data, dict)
            and {
                "confirmed_settlement_income",
                "current_pending_receivables",
            }
            <= result_data.keys()
        ):
            for settlement_field in settlement_fields:
                if settlement_field not in fields:
                    fields.append(settlement_field)
        rendered_fields: list[str] = []
        for field in fields:
            if not isinstance(field, str) or not field.strip():
                raise ValueError("能力缺口回答字段路径无效")
            current: object = results[result_id]
            for part in field.split("."):
                if not isinstance(current, dict) or part not in current:
                    raise ValueError("能力缺口回答引用的字段不存在")
                current = current[part]
            presentation = _CAPABILITY_FIELD_PRESENTATION.get(field)
            if presentation is None and field.startswith("values."):
                presentation = ("派生计算结果", "")
            if isinstance(current, list):
                list_label = _CAPABILITY_LIST_PRESENTATION.get(field)
                if list_label is None:
                    raise ValueError("能力缺口回答列表字段不允许直接展示")
                rows: list[str] = []
                for row in current:
                    if not isinstance(row, dict):
                        raise ValueError("能力缺口回答列表结构无效")
                    values: list[str] = []
                    for key, value in row.items():
                        row_presentation = (
                            _CAPABILITY_ROW_FIELD_PRESENTATION.get(key)
                        )
                        if row_presentation is None or isinstance(
                            value, (dict, list)
                        ):
                            continue
                        row_label, row_unit = row_presentation
                        if value is None:
                            rendered = "不可用"
                            row_unit = ""
                        elif key == "status":
                            rendered = {
                                "active": "使用中",
                                "archived": "已归档",
                                "pending": "待到账",
                                "confirmed": "已确认",
                            }.get(str(value), str(value))
                        elif isinstance(value, bool):
                            rendered = "是" if value else "否"
                        else:
                            rendered = str(value)
                        values.append(
                            f"{row_label}为 {rendered}{row_unit}"
                        )
                    if values:
                        rows.append("、".join(values))
                rendered_fields.append(
                    f"{list_label}："
                    + ("；".join(rows) if rows else "没有匹配结果")
                )
            else:
                if presentation is None or isinstance(current, dict):
                    raise ValueError("能力缺口回答字段不允许直接展示")
                label, unit = presentation
                if current is None:
                    rendered = "不可用"
                    unit = ""
                elif isinstance(current, bool):
                    rendered = "是" if current else "否"
                else:
                    rendered = str(current)
                rendered_fields.append(f"{label}为 {rendered}{unit}")
            submitted_fields.add(field)
        accepted.append(
            f"根据本轮结果编号 {result_id}，可确认："
            + "；".join(rendered_fields)
            + "。"
        )
    if settlement_fields <= submitted_fields:
        accepted.append("当前待到账应收款不计入营业额或月度总收入。")
    return capability_gap_answer(missing_capabilities, accepted)


def _trusted_limit_answer(
    results: dict[str, dict[str, Any]],
    limitation: str,
) -> str:
    evidence: list[dict[str, object]] = []
    for result_id, result in results.items():
        fields: list[str] = []
        for field in (
            *_CAPABILITY_FIELD_PRESENTATION,
            *_CAPABILITY_LIST_PRESENTATION,
        ):
            current: object = result
            for part in field.split("."):
                if not isinstance(current, dict) or part not in current:
                    break
                current = current[part]
            else:
                fields.append(field)
        if fields:
            evidence.append({"result_id": result_id, "fields": fields})
    if not evidence:
        return (
            "本轮尚未取得可安全展示的业务结果，无法提供未经验证的数值或判断。"
            f"\n\n限制说明：本轮已达到{limitation}。"
        )
    answer = _submitted_capability_answer(
        {"evidence": evidence},
        results=results,
        missing_capabilities=(limitation,),
    )
    supported, _, _boundary = answer.partition("\n\n能力边界：")
    return (
        f"{supported}\n\n限制说明：本轮已达到{limitation}，"
        "回答仅包含当前已取得的可信结果。"
    )


@dataclass
class _ActiveTurn:
    turn_id: int
    events: asyncio.Queue[TurnEvent | object]
    task: asyncio.Task[None] | None = None


def _finished_now() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


async def _one_chunk(value: str) -> AsyncIterator[str]:
    yield value


async def _validated_answer_chunks(
    chunks: AsyncIterator[str],
    *,
    user_content: str,
    loaded_skills: dict[str, Any],
    results: dict[str, dict[str, Any]],
) -> AsyncIterator[str]:
    full_answer: list[str] = []
    validation_context = ""
    held_chunks: list[str] = []
    async for chunk in chunks:
        full_answer.append(chunk)
        validation_context += chunk
        held_chunks.append(chunk)
        boundaries = list(re.finditer(r"[。！？\n]+", validation_context))
        if boundaries:
            boundary = boundaries[-1].end()
            _validate_business_answer(
                validation_context[:boundary],
                user_content=user_content,
                loaded_skills=loaded_skills,
                results=results,
            )
            for held_chunk in held_chunks:
                yield held_chunk
            held_chunks.clear()
            validation_context = validation_context[boundary:]
        elif not any(character.isdigit() for character in "".join(held_chunks)):
            for held_chunk in held_chunks:
                yield held_chunk
            held_chunks.clear()
    _validate_business_answer(
        "".join(full_answer),
        user_content=user_content,
        loaded_skills=loaded_skills,
        results=results,
    )
    for held_chunk in held_chunks:
        yield held_chunk


async def latest_conversation_turn(
    session: AsyncSession,
    conversation_id: int,
) -> AgentTurn | None:
    return await session.scalar(
        select(AgentTurn)
        .where(AgentTurn.conversation_id == conversation_id)
        .order_by(AgentTurn.id.desc())
        .limit(1)
    )


class AgentTurnRuntime:
    def __init__(
        self,
        session_factory: SessionFactory,
        adapter_factory: AdapterFactory,
        *,
        turn_timeout_seconds: float = 120,
        stop_new_tools_seconds: float = 90,
        model_round_limit: int = 8,
        data_tool_call_limit: int = 12,
        data_tool_timeout_seconds: float = 10,
        transient_retry_limit: int = 1,
        data_tools: AgentDataToolRegistry | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._adapter_factory = adapter_factory
        self._turn_timeout_seconds = turn_timeout_seconds
        self._stop_new_tools_seconds = stop_new_tools_seconds
        self._model_round_limit = model_round_limit
        self._data_tool_call_limit = data_tool_call_limit
        self._data_tool_timeout_seconds = data_tool_timeout_seconds
        self._transient_retry_limit = transient_retry_limit
        self._data_tools = data_tools or AgentDataToolRegistry(session_factory)
        self._skills = SkillCatalog(self._data_tools.names)
        self._active: dict[tuple[int, int], _ActiveTurn] = {}
        self._starting: set[tuple[int, int]] = set()
        self._lock = asyncio.Lock()

    async def recover_interrupted_turns(self) -> None:
        async with self._session_factory() as session:
            async with sqlite_short_write(session):
                await session.execute(
                    update(AgentTurn)
                    .where(AgentTurn.status == "running")
                    .values(
                        status="interrupted",
                        error_message=TURN_INTERRUPTED_MESSAGE,
                        finished_at=_finished_now(),
                    )
                )

    async def start(
        self,
        *,
        user_id: int,
        store_id: int,
        content: str,
    ) -> AsyncIterator[bytes]:
        key = (user_id, store_id)
        started_at = asyncio.get_running_loop().time()
        deadline = started_at + self._turn_timeout_seconds
        tool_start_deadline = started_at + self._stop_new_tools_seconds
        async with self._lock:
            if key in self._active or key in self._starting:
                raise ActiveAgentTurnError
            self._starting.add(key)

        try:
            async with asyncio.timeout_at(deadline):
                (
                    turn_id,
                    model_messages,
                    direct_answer,
                    missing_capabilities,
                ) = (
                    await self._persist_start(
                        user_id=user_id,
                        store_id=store_id,
                        content=content,
                    )
                )
            active = _ActiveTurn(turn_id=turn_id, events=asyncio.Queue())
            async with self._lock:
                self._active[key] = active
                self._starting.remove(key)
                active.task = asyncio.create_task(
                    self._run(
                        key=key,
                        active=active,
                        model_messages=model_messages,
                        user_content=content,
                        direct_answer=direct_answer,
                        missing_capabilities=missing_capabilities,
                        deadline=deadline,
                        tool_start_deadline=tool_start_deadline,
                    )
                )
        except TimeoutError as exc:
            async with self._lock:
                self._starting.discard(key)
            raise AgentTurnStartTimeoutError from exc
        except BaseException:
            async with self._lock:
                self._starting.discard(key)
            raise

        return self._event_stream(active)

    async def stop(self) -> None:
        async with self._lock:
            tasks = [
                active.task
                for active in self._active.values()
                if active.task is not None
            ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    async def _persist_start(
        self,
        *,
        user_id: int,
        store_id: int,
        content: str,
    ) -> tuple[
        int,
        list[ModelMessage],
        str | None,
        tuple[str, ...],
    ]:
        async with self._session_factory() as session:
            store = await session.get(Store, store_id)
            if store is None:
                raise RuntimeError("Agent current store disappeared")
            store_local_date = datetime.now(
                ZoneInfo(store.timezone)
            ).date()
            system_context = trusted_store_context(store)
            system_context["content"] += (
                "\n\n可按需加载的数据 Skill：\n"
                f"{self._skills.summaries()}\n"
                "先调用 load_skill 获取完整规则，再调用该 Skill 允许的数据工具。"
            )
            conversation = await get_or_create_conversation(
                session,
                user_id=user_id,
                store_id=store_id,
            )
            conversation_id = conversation.id
            history = await conversation_messages(session, conversation_id)
            time_scope = interpret_time_scope(
                content,
                local_date=store_local_date,
            )
            missing_capabilities = capability_gap_terms(content)
            additional_context = list(time_scope.guidance)
            investigation_context = await relevant_investigation_context(
                session,
                conversation_id,
                content,
            )
            if investigation_context is not None:
                additional_context.append(investigation_context)
            gap_guidance = capability_gap_guidance(missing_capabilities)
            if gap_guidance is not None:
                additional_context.append(gap_guidance)
            model_messages = bounded_model_context(
                system_context=system_context,
                summary=conversation.context_summary,
                history=history,
                content=content,
                additional_system_context=additional_context,
            )
            direct_answer = (
                (
                    time_scope.direct_answer
                    if time_scope.direct_answer is not None
                    else None
                )
                if is_business_scope_question(content)
                else AGENT_SCOPE_EXPLANATION
            )
            async with sqlite_short_write(session):
                user_message = AgentMessage(
                    conversation_id=conversation_id,
                    role="user",
                    content=content,
                )
                session.add(user_message)
                await session.flush()
                turn = AgentTurn(
                    conversation_id=conversation_id,
                    user_message_id=user_message.id,
                    status="running",
                )
                session.add(turn)
                await session.flush()
                turn_id = turn.id
        return (
            turn_id,
            model_messages,
            direct_answer,
            missing_capabilities,
        )

    async def _run(
        self,
        *,
        key: tuple[int, int],
        active: _ActiveTurn,
        model_messages: Sequence[ModelMessage],
        user_content: str,
        direct_answer: str | None,
        missing_capabilities: tuple[str, ...],
        deadline: float,
        tool_start_deadline: float,
    ) -> None:
        chunks: list[str] = []
        cards: list[dict[str, Any]] = []
        trusted_results: dict[str, dict[str, Any]] = {}
        try:
            async with asyncio.timeout_at(deadline):
                await active.events.put(
                    {"type": "started", "turn_id": active.turn_id}
                )
                if direct_answer is not None:
                    await active.events.put(
                        {
                            "type": "phase",
                            "turn_id": active.turn_id,
                            "phase": "preparing_answer",
                        }
                    )
                    chunks.append(direct_answer)
                    await active.events.put(
                        {
                            "type": "answer_delta",
                            "turn_id": active.turn_id,
                            "delta": direct_answer,
                        }
                    )
                else:
                    await active.events.put(
                        {
                            "type": "phase",
                            "turn_id": active.turn_id,
                            "phase": "querying_data",
                        }
                    )
                    adapter = self._adapter_factory()
                    if callable(getattr(adapter, "respond", None)):
                        answer, cards = await self._run_tool_loop(
                            adapter=adapter,
                            active=active,
                            model_messages=model_messages,
                            user_content=user_content,
                            user_id=key[0],
                            store_id=key[1],
                            missing_capabilities=missing_capabilities,
                            tool_start_deadline=tool_start_deadline,
                            results=trusted_results,
                            cards=cards,
                        )
                        chunks.append(answer)
                    else:
                        emitted_answer_phase = False
                        if missing_capabilities:
                            model_chunks = _one_chunk(
                                capability_gap_answer(missing_capabilities)
                            )
                        else:
                            model_chunks = _validated_answer_chunks(
                                self._model_chunks(
                                    adapter,
                                    model_messages,
                                ),
                                user_content=user_content,
                                loaded_skills={},
                                results=trusted_results,
                            )
                        async for chunk in model_chunks:
                            if not chunk:
                                continue
                            if not emitted_answer_phase:
                                for phase in (
                                    "processing_data",
                                    "preparing_answer",
                                ):
                                    await active.events.put(
                                        {
                                            "type": "phase",
                                            "turn_id": active.turn_id,
                                            "phase": phase,
                                        }
                                    )
                                emitted_answer_phase = True
                            chunks.append(chunk)
                            await active.events.put(
                                {
                                    "type": "answer_delta",
                                    "turn_id": active.turn_id,
                                    "delta": chunk,
                                }
                            )
                answer = "".join(chunks).strip()
                if not answer:
                    raise ValueError("Agent model returned an empty answer")
                await self._persist_completion(
                    active.turn_id,
                    answer,
                    cards=cards if direct_answer is None else (),
                )
            await active.events.put(
                {"type": "completed", "turn_id": active.turn_id}
            )
        except TimeoutError:
            await self._finish_timed_out_turn(
                active,
                chunks,
                results=trusted_results,
                cards=cards,
            )
        except asyncio.CancelledError:
            await self._persist_failure_bounded(
                active.turn_id,
                status="interrupted",
                message=TURN_INTERRUPTED_MESSAGE,
            )
            raise
        except Exception:
            logger.exception("Agent turn failed")
            await self._persist_failure_bounded(
                active.turn_id,
                status="failed",
                message=TURN_FAILED_MESSAGE,
            )
            await active.events.put(
                {
                    "type": "failed",
                    "turn_id": active.turn_id,
                    "message": TURN_FAILED_MESSAGE,
                }
            )
        finally:
            await active.events.put(_END)
            async with self._lock:
                if self._active.get(key) is active:
                    del self._active[key]

    @staticmethod
    def _model_tools() -> tuple[ModelTool, ...]:
        return (
            {
                "type": "function",
                "function": {
                    "name": "submit_answer",
                    "description": (
                        "能力缺口问题的最终回答提交。选择本轮结果编号及其中"
                        "要展示的字段；后端生成可信段落并追加能力缺口说明。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "evidence": {
                                "type": "array",
                                "maxItems": 20,
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "result_id": {"type": "string"},
                                        "fields": {
                                            "type": "array",
                                            "minItems": 1,
                                            "maxItems": 20,
                                            "items": {"type": "string"},
                                        },
                                    },
                                    "required": ["result_id", "fields"],
                                    "additionalProperties": False,
                                },
                            }
                        },
                        "required": ["evidence"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "load_skill",
                    "description": "按名称加载一个数据 Skill 的完整规则。",
                    "parameters": {
                        "type": "object",
                        "properties": {"name": {"type": "string"}},
                        "required": ["name"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "business_performance_summary",
                    "description": "汇总 Agent 当前门店指定期间的经营表现。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "ledger_revenue_trend",
                    "description": "按日或按月返回 Agent 当前门店的台账营业额趋势。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                            "bucket": {
                                "type": "string",
                                "enum": ["day", "month"],
                            },
                        },
                        "required": ["start", "end", "bucket"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "income_composition",
                    "description": "返回收入分类和其他数据的历史构成。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "daily_ledger_detail",
                    "description": "按业务筛选返回有界、可分页的每日台账明细。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                            "operating_statuses": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["营业", "休息", "提前休息"],
                                },
                                "maxItems": 3,
                            },
                            "recorded_weather": {"type": "string"},
                            "events_only": {"type": "boolean"},
                            "event_keyword": {"type": "string"},
                            "missing_wash_count": {"type": "boolean"},
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 50,
                            },
                            "offset": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 10000,
                            },
                        },
                        "required": ["start", "end"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "business_context_group",
                    "description": (
                        "按星期或记录天气分组返回 Agent 当前门店经营日的"
                        "台账营业额和经营日均台账营业额。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start": {"type": "string", "format": "date"},
                            "end": {"type": "string", "format": "date"},
                            "dimension": {
                                "type": "string",
                                "enum": ["weekday", "recorded_weather"],
                            },
                        },
                        "required": ["start", "end", "dimension"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "company_settlement_summary",
                    "description": (
                        "按开票月份或结算公司分别汇总已确认公司结算收入和"
                        "当前待到账应收款。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_month": {
                                "type": "string",
                                "pattern": r"^\d{4}-(0[1-9]|1[0-2])$",
                            },
                            "end_month": {
                                "type": "string",
                                "pattern": r"^\d{4}-(0[1-9]|1[0-2])$",
                            },
                            "group_by": {
                                "type": "string",
                                "enum": ["opening_month", "company"],
                            },
                        },
                        "required": [
                            "start_month",
                            "end_month",
                            "group_by",
                        ],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "company_settlement_detail",
                    "description": (
                        "按开票月份、结算公司和当前状态返回有界、可分页的"
                        "公司结算明细。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "start_month": {
                                "type": "string",
                                "pattern": r"^\d{4}-(0[1-9]|1[0-2])$",
                            },
                            "end_month": {
                                "type": "string",
                                "pattern": r"^\d{4}-(0[1-9]|1[0-2])$",
                            },
                            "company_id": {
                                "type": "integer",
                                "minimum": 1,
                            },
                            "statuses": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["pending", "confirmed"],
                                },
                                "minItems": 1,
                                "maxItems": 2,
                                "uniqueItems": True,
                            },
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 50,
                            },
                            "offset": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 10000,
                            },
                        },
                        "required": ["start_month", "end_month"],
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "settlement_company_directory",
                    "description": (
                        "返回 Agent 当前门店使用中或已归档的结算公司目录。"
                    ),
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "statuses": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": ["active", "archived"],
                                },
                                "minItems": 1,
                                "maxItems": 2,
                                "uniqueItems": True,
                            },
                            "limit": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": 50,
                            },
                            "offset": {
                                "type": "integer",
                                "minimum": 0,
                                "maximum": 10000,
                            },
                        },
                        "additionalProperties": False,
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "calculate",
                    "description": "引用本轮结果或标明来源的字面量执行受限十进制计算。",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "steps": {
                                "type": "array",
                                "items": {"type": "object"},
                            }
                        },
                        "required": ["steps"],
                        "additionalProperties": False,
                    },
                },
            },
        )

    async def _run_tool_loop(
        self,
        *,
        adapter: AgentModelAdapter,
        active: _ActiveTurn,
        model_messages: Sequence[ModelMessage],
        user_content: str,
        user_id: int,
        store_id: int,
        missing_capabilities: tuple[str, ...],
        tool_start_deadline: float,
        results: dict[str, dict[str, Any]],
        cards: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        messages = list(model_messages)
        loaded_skills = {}
        result_number = 0
        data_tool_calls = 0
        for _round in range(self._model_round_limit):
            messages = fit_model_context(messages)
            response_content: list[str] = []
            response_tool_calls: list[ModelToolCall] = []
            streamed_answer = False
            answer_validation_context = ""
            held_answer_chunks: list[str] = []
            async for response_part in self._respond_events_with_retry(
                adapter,
                messages,
                self._model_tools(),
            ):
                if response_part.tool_calls:
                    if response_content:
                        raise ValueError(
                            "Agent model mixed answer text and tool calls"
                        )
                    response_tool_calls.extend(response_part.tool_calls)
                    continue
                chunk = response_part.content or ""
                if not chunk:
                    continue
                if response_tool_calls:
                    raise ValueError(
                        "Agent model mixed answer text and tool calls"
                    )
                response_content.append(chunk)
                if (
                    not missing_capabilities
                    and "company_settlement" not in loaded_skills
                ):
                    answer_validation_context += chunk
                    held_answer_chunks.append(chunk)
                    boundaries = list(
                        re.finditer(
                            r"[。！？\n]+",
                            answer_validation_context,
                        )
                    )
                    can_release = False
                    if boundaries:
                        boundary = boundaries[-1].end()
                        _validate_business_answer(
                            answer_validation_context[:boundary],
                            user_content=user_content,
                            loaded_skills=loaded_skills,
                            results=results,
                        )
                        answer_validation_context = (
                            answer_validation_context[boundary:]
                        )
                        can_release = True
                    elif not any(
                        character.isdigit()
                        for character in "".join(held_answer_chunks)
                    ):
                        can_release = True
                    if can_release:
                        if not streamed_answer:
                            await self._emit_answer_phases(active)
                            streamed_answer = True
                        for held_chunk in held_answer_chunks:
                            await active.events.put(
                                {
                                    "type": "answer_delta",
                                    "turn_id": active.turn_id,
                                    "delta": held_chunk,
                                }
                            )
                        held_answer_chunks.clear()
            response = ModelResponse(
                content="".join(response_content) or None,
                tool_calls=tuple(response_tool_calls),
            )
            if not response.tool_calls:
                answer = (response.content or "").strip()
                if not answer:
                    raise ValueError("Agent model returned an empty answer")
                if missing_capabilities:
                    answer = capability_gap_answer(missing_capabilities)
                _validate_business_answer(
                    answer,
                    user_content=user_content,
                    loaded_skills=loaded_skills,
                    results=results,
                )
                if missing_capabilities:
                    await self._emit_trusted_answer(active, answer)
                elif "company_settlement" in loaded_skills:
                    await self._emit_trusted_answer_fragments(active, answer)
                else:
                    if held_answer_chunks:
                        if not streamed_answer:
                            await self._emit_answer_phases(active)
                        for held_chunk in held_answer_chunks:
                            await active.events.put(
                                {
                                    "type": "answer_delta",
                                    "turn_id": active.turn_id,
                                    "delta": held_chunk,
                                }
                            )
                return answer, cards

            submit_calls = [
                call
                for call in response.tool_calls
                if call.name == "submit_answer"
            ]
            if submit_calls:
                if (
                    not missing_capabilities
                    or len(response.tool_calls) != 1
                    or len(submit_calls) != 1
                ):
                    raise ValueError("submit_answer 只能单独用于能力缺口最终回答")
                try:
                    answer = _submitted_capability_answer(
                        submit_calls[0].arguments,
                        results=results,
                        missing_capabilities=missing_capabilities,
                    )
                except ValueError:
                    answer = capability_gap_answer(missing_capabilities)
                _validate_business_answer(
                    answer,
                    user_content=user_content,
                    loaded_skills=loaded_skills,
                    results=results,
                )
                await self._emit_trusted_answer(active, answer)
                return answer, cards

            messages.append(
                {
                    "role": "assistant",
                    "content": response.content,
                    "tool_calls": [
                        {
                            "id": call.id,
                            "type": "function",
                            "function": {
                                "name": call.name,
                                "arguments": json.dumps(
                                    call.arguments,
                                    ensure_ascii=False,
                                    separators=(",", ":"),
                                ),
                            },
                        }
                        for call in response.tool_calls
                    ],
                }
            )
            for call in response.tool_calls:
                if (
                    asyncio.get_running_loop().time()
                    >= tool_start_deadline
                ):
                    answer = _trusted_limit_answer(
                        results,
                        "停止发起新工具时限",
                    )
                    await self._emit_trusted_answer(active, answer)
                    return answer, cards
                if call.name == "load_skill":
                    if set(call.arguments) != {"name"}:
                        raise ValueError("数据 Skill 加载参数无效")
                    skill = self._skills.load(str(call.arguments["name"]))
                    loaded_skills[skill.name] = skill
                    tool_result = {
                        "name": skill.name,
                        "instructions": skill.instructions,
                        "allowed_data_tools": sorted(
                            skill.allowed_data_tools
                        ),
                    }
                elif call.name in self._data_tools.names:
                    if data_tool_calls >= self._data_tool_call_limit:
                        answer = _trusted_limit_answer(
                            results,
                            "数据工具次数上限",
                        )
                        await self._emit_trusted_answer(active, answer)
                        return answer, cards
                    if not any(
                        call.name in skill.allowed_data_tools
                        for skill in loaded_skills.values()
                    ):
                        raise ValueError("数据工具未获得已加载 Skill 授权")
                    data_tool_calls += 1
                    result_number += 1
                    result_id = f"result-{result_number}"
                    try:
                        tool_result = await self._execute_data_tool_with_retry(
                            call.name,
                            call.arguments,
                            context=DataToolContext(
                                user_id=user_id,
                                store_id=store_id,
                            ),
                            result_id=result_id,
                        )
                    except Exception as exc:
                        error_category = self._safe_tool_error_category(exc)
                        tool_result = {
                            "status": "failed",
                            "error_category": error_category,
                        }
                        card = self._data_tools.investigation_failure_card(
                            call.name,
                            error_category,
                        )
                    else:
                        results[result_id] = tool_result
                        card = self._data_tools.investigation_card(
                            call.name,
                            call.arguments,
                            tool_result,
                        )
                    cards.append(card)
                    await active.events.put(
                        {
                            "type": "investigation_card",
                            "turn_id": active.turn_id,
                            "card": card,
                        }
                    )
                elif call.name == "calculate":
                    if set(call.arguments) != {"steps"}:
                        raise ValueError("派生计算参数无效")
                    _validate_settlement_calculation(
                        call.arguments["steps"],
                        user_content=str(model_messages[-1].get("content", "")),
                    )
                    result_number += 1
                    result_id = f"result-{result_number}"
                    calculation = calculate(
                        call.arguments["steps"],
                        results=results,
                    )
                    tool_result = {
                        "result_id": result_id,
                        **calculation,
                    }
                    results[result_id] = tool_result
                    calculation_unavailable = bool(
                        calculation["unavailable"]
                    )
                    card = {
                        "operation": "完成派生计算",
                        "range_start": None,
                        "range_end": None,
                        "filters": [],
                        "status": (
                            "unavailable"
                            if calculation_unavailable
                            else "completed"
                        ),
                    }
                    if calculation_unavailable:
                        card["error_category"] = "expected_unavailable"
                    cards.append(card)
                    await active.events.put(
                        {
                            "type": "investigation_card",
                            "turn_id": active.turn_id,
                            "card": card,
                        }
                    )
                else:
                    if not missing_capabilities:
                        raise ValueError("模型调用了未知工具")
                    tool_result = {
                        "status": "unavailable",
                        "reason": (
                            "该能力不在当前数据 Skill 和数据工具范围内；"
                            "请使用已有可信结果回答可确认部分并明确说明缺口。"
                        ),
                        "requested_tool": call.name,
                    }
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(
                            tool_result,
                            ensure_ascii=False,
                            separators=(",", ":"),
                        ),
                    }
                )
        answer = _trusted_limit_answer(results, "模型轮数上限")
        await self._emit_trusted_answer(active, answer)
        return answer, cards

    @staticmethod
    async def _emit_answer_phases(
        active: _ActiveTurn,
    ) -> None:
        for phase in ("processing_data", "preparing_answer"):
            await active.events.put(
                {
                    "type": "phase",
                    "turn_id": active.turn_id,
                    "phase": phase,
                }
            )

    @classmethod
    async def _emit_trusted_answer(
        cls,
        active: _ActiveTurn,
        answer: str,
    ) -> None:
        await cls._emit_answer_phases(active)
        await active.events.put(
            {
                "type": "answer_delta",
                "turn_id": active.turn_id,
                "delta": answer,
            }
        )

    @classmethod
    async def _emit_trusted_answer_fragments(
        cls,
        active: _ActiveTurn,
        answer: str,
    ) -> None:
        await cls._emit_answer_phases(active)
        fragments = re.findall(r".*?(?:[。！？\n]+|$)", answer, flags=re.DOTALL)
        for fragment in fragments:
            if not fragment:
                continue
            await active.events.put(
                {
                    "type": "answer_delta",
                    "turn_id": active.turn_id,
                    "delta": fragment,
                }
            )

    async def _finish_timed_out_turn(
        self,
        active: _ActiveTurn,
        chunks: list[str],
        *,
        results: dict[str, dict[str, Any]],
        cards: list[dict[str, Any]],
    ) -> None:
        if not chunks:
            chunks.append(
                _trusted_limit_answer(results, "总轮次处理时限")
            )
            await active.events.put(
                {
                    "type": "answer_delta",
                    "turn_id": active.turn_id,
                    "delta": chunks[-1],
                }
            )
        if chunks:
            if "总轮次处理时限" not in chunks[-1]:
                timeout_note = (
                    "\n\n（本轮已达到处理时限，以上为当前可用结果。）"
                )
                chunks.append(timeout_note)
                await active.events.put(
                    {
                        "type": "answer_delta",
                        "turn_id": active.turn_id,
                        "delta": timeout_note,
                    }
                )
            try:
                async with asyncio.timeout(self._cleanup_timeout_seconds):
                    await self._persist_completion(
                        active.turn_id,
                        "".join(chunks).strip(),
                        cards=cards,
                    )
            except Exception:
                await self._emit_failed_turn(active)
                return
            await active.events.put(
                {
                    "type": "completed",
                    "turn_id": active.turn_id,
                    "partial": True,
                }
            )
            return
        await self._emit_failed_turn(active)

    @property
    def _cleanup_timeout_seconds(self) -> float:
        return min(5.0, max(0.1, self._turn_timeout_seconds))

    async def _emit_failed_turn(self, active: _ActiveTurn) -> None:
        await self._persist_failure_bounded(
            active.turn_id,
            status="failed",
            message=TURN_FAILED_MESSAGE,
        )
        await active.events.put(
            {
                "type": "failed",
                "turn_id": active.turn_id,
                "message": TURN_FAILED_MESSAGE,
            }
        )

    async def _persist_failure_bounded(
        self,
        turn_id: int,
        *,
        status: str,
        message: str,
    ) -> None:
        try:
            async with asyncio.timeout(self._cleanup_timeout_seconds):
                await self._persist_failure(
                    turn_id,
                    status=status,
                    message=message,
                )
        except Exception:
            return

    async def _model_chunks(
        self,
        adapter: AgentModelAdapter,
        model_messages: Sequence[ModelMessage],
    ) -> AsyncIterator[str]:
        fitted_messages = fit_model_context(model_messages)
        for attempt in range(self._transient_retry_limit + 1):
            emitted = False
            try:
                stream = getattr(adapter, "stream", None)
                if stream is None:
                    answer = await adapter.complete(fitted_messages)
                    emitted = True
                    yield answer
                else:
                    async for chunk in stream(fitted_messages):
                        emitted = True
                        yield chunk
                return
            except Exception as exc:
                if (
                    attempt < self._transient_retry_limit
                    and not emitted
                    and self._is_transient_model_error(exc)
                ):
                    continue
                raise

    async def _respond_with_retry(
        self,
        adapter: AgentModelAdapter,
        messages: Sequence[ModelMessage],
        tools: Sequence[ModelTool],
    ) -> ModelResponse:
        for attempt in range(self._transient_retry_limit + 1):
            try:
                return await adapter.respond(messages, tools)
            except Exception as exc:
                if (
                    attempt >= self._transient_retry_limit
                    or not self._is_transient_model_error(exc)
                ):
                    raise
        raise RuntimeError("unreachable model retry state")

    async def _respond_events_with_retry(
        self,
        adapter: AgentModelAdapter,
        messages: Sequence[ModelMessage],
        tools: Sequence[ModelTool],
    ) -> AsyncIterator[ModelResponse]:
        stream_response = getattr(adapter, "respond_stream", None)
        if not callable(stream_response):
            yield await self._respond_with_retry(adapter, messages, tools)
            return
        for attempt in range(self._transient_retry_limit + 1):
            emitted = False
            try:
                async for response in stream_response(messages, tools):
                    emitted = True
                    yield response
                return
            except Exception as exc:
                if (
                    attempt < self._transient_retry_limit
                    and not emitted
                    and self._is_transient_model_error(exc)
                ):
                    continue
                raise

    async def _execute_data_tool_with_retry(
        self,
        name: str,
        arguments: dict[str, Any],
        *,
        context: DataToolContext,
        result_id: str,
    ) -> dict[str, Any]:
        for attempt in range(self._transient_retry_limit + 1):
            try:
                async with asyncio.timeout(
                    self._data_tool_timeout_seconds
                ):
                    return await self._data_tools.execute(
                        name,
                        arguments,
                        context=context,
                        result_id=result_id,
                    )
            except Exception as exc:
                if (
                    attempt >= self._transient_retry_limit
                    or not self._is_transient_model_error(exc)
                ):
                    raise
        raise RuntimeError("unreachable data-tool retry state")

    @classmethod
    def _safe_tool_error_category(cls, exc: Exception) -> str:
        if isinstance(exc, TimeoutError):
            return "timeout"
        if cls._is_transient_model_error(exc):
            return "temporary"
        if isinstance(exc, PermissionError):
            return "permission"
        if isinstance(exc, ValueError):
            return "validation"
        return "tool_failure"

    @staticmethod
    def _is_transient_model_error(exc: Exception) -> bool:
        if isinstance(exc, httpx.HTTPStatusError):
            status = exc.response.status_code
            return status == 429 or status >= 500
        return isinstance(exc, httpx.RequestError)

    async def _persist_completion(
        self,
        turn_id: int,
        answer: str,
        *,
        cards: Sequence[dict[str, Any]] = (),
    ) -> None:
        async with self._session_factory() as session:
            turn = await session.get(AgentTurn, turn_id)
            if turn is None:
                raise RuntimeError("Agent turn disappeared")
            if turn.status == "completed":
                return
            conversation_id = turn.conversation_id
            async with sqlite_short_write(session):
                assistant_message = AgentMessage(
                    conversation_id=conversation_id,
                    role="assistant",
                    content=answer,
                )
                session.add(assistant_message)
                await session.flush()
                for card in cards:
                    session.add(
                        AgentInvestigationCard(
                            turn_id=turn_id,
                            operation=card["operation"],
                            range_start=card["range_start"],
                            range_end=card["range_end"],
                            filters_json=json.dumps(
                                card["filters"],
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                            status=card["status"],
                            error_category=card.get("error_category"),
                        )
                    )
                turn.assistant_message_id = assistant_message.id
                turn.status = "completed"
                turn.error_message = None
                turn.finished_at = _finished_now()
                await refresh_context_summary(session, conversation_id)

    async def _persist_failure(
        self,
        turn_id: int,
        *,
        status: str,
        message: str,
    ) -> None:
        async with self._session_factory() as session:
            turn = await session.get(AgentTurn, turn_id)
            if turn is None:
                return
            async with sqlite_short_write(session):
                turn.status = status
                turn.error_message = message
                turn.finished_at = _finished_now()

    async def _event_stream(
        self,
        active: _ActiveTurn,
    ) -> AsyncIterator[bytes]:
        while True:
            event = await active.events.get()
            if event is _END:
                return
            yield (
                json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            ).encode()
