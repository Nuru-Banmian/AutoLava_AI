from __future__ import annotations

import asyncio
import hashlib
import json
import re
from calendar import monthrange
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Any, Literal, Protocol
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.agent.answer_grounding import NativeAnswerClaim, answer_is_grounded
from app.agent.conversation import AgentRunResult, ConfirmedPeriod, ConversationState
from app.agent.contracts import (
    CurrentStoreScope,
    AverageRevenuePerCarResult,
    CategoryAmountResult,
    DailyLedgerRevenueResult,
    DailyLedgerExtremeResult,
    EVIDENCE_METRIC_LABELS,
    EvidenceBundle,
    EvidenceCoverage,
    EvidenceCompleteness,
    EvidenceFilters,
    EvidenceGroup,
    EvidenceMetric,
    EvidencePeriodResult,
    EvidencePlan,
    ConfirmedSettlementIncomeResult,
    GroupedMetricResult,
    ModelMessage,
    MonthlyTotalRevenueResult,
    MonthlyDailyAverageIncomeResult,
    OperatingDayAverageLedgerRevenueResult,
    OperatingDaysResult,
    WashCountResult,
    TurnResult,
)
from app.agent.runtime import RuntimeContext

MONTHLY_TOTAL_REVENUE_TOOL = "monthly_total_revenue"
DAILY_LEDGER_REVENUE_TOOL = "daily_ledger_revenue"
CONFIRMED_SETTLEMENT_INCOME_TOOL = "confirmed_settlement_income"
OPERATING_DAYS_TOOL = "operating_days"
OPERATING_DAY_AVERAGE_LEDGER_REVENUE_TOOL = "operating_day_average_ledger_revenue"
MONTHLY_DAILY_AVERAGE_INCOME_TOOL = "monthly_daily_average_income"
WASH_COUNT_TOOL = "wash_count"
AVERAGE_REVENUE_PER_CAR_TOOL = "average_revenue_per_car"
INCOME_CATEGORY_AMOUNT_TOOL = "income_category_amount"
OTHER_DATA_AMOUNT_TOOL = "other_data_amount"
DAILY_LEDGER_REVENUE_EXTREME_TOOL = "daily_ledger_revenue_extreme"
MAX_NATIVE_TOOL_ROUNDS = 4
MAX_NATIVE_TOOL_CALLS = 8
INVESTIGATION_LIMIT_MESSAGE = "调查已达到本轮资源上限；以下结论仅基于已返回的证据。"
ANSWER_EVIDENCE_FAILURE_MESSAGE = "回答中的关键经营声明缺少本轮有效证据支持，请缩小范围后重试。"
EXPLICIT_CALENDAR_MONTH = re.compile(
    r"(?P<year>20\d{2}|21\d{2}|2200)\s*年\s*(?P<month>1[0-2]|0?[1-9])\s*月"
)
EXACT_MONTH_CLARIFICATION = "请提供要查询的准确自然月，例如“2026 年 7 月”。"


class NativeToolAccessDenied(RuntimeError):
    """A non-retryable authorization or tool-contract failure."""


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class NativeToolDefinition(ClosedModel):
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(min_length=1, max_length=1_000)
    input_schema: dict[str, Any]


class NativeToolCall(ClosedModel):
    id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    arguments: dict[str, Any]


class MonthlyTotalRevenueArguments(ClosedModel):
    year: int = Field(ge=2000, le=2200)
    month: int = Field(ge=1, le=12)


class ComposableBusinessMetricArguments(MonthlyTotalRevenueArguments):
    group_by: EvidenceGroup | None = None
    filters: EvidenceFilters | None = None


class DailyLedgerRevenueExtremeArguments(MonthlyTotalRevenueArguments):
    extreme: Literal["highest", "lowest"]
    filters: EvidenceFilters | None = None


StoreFeatureFlag = Literal[
    "company_settlement_enabled",
    "income_items_enabled",
    "wash_count_enabled",
]


@dataclass(frozen=True)
class NativeToolRegistration:
    definition: NativeToolDefinition
    required_features: frozenset[StoreFeatureFlag]

    def is_available(self, context: RuntimeContext) -> bool:
        if context.role not in {"admin", "final_admin"} or not context.features.agent_enabled:
            return False
        try:
            ZoneInfo(context.store_timezone)
        except ZoneInfoNotFoundError:
            return False
        return all(getattr(context.features, feature) for feature in self.required_features)


class NativeAnalysisHypothesis(ClosedModel):
    statement: str = Field(min_length=1, max_length=500)
    status: Literal["proposed", "testing", "supported", "refuted", "unresolved"]
    evidence_references: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_supported_evidence(self) -> NativeAnalysisHypothesis:
        if any(
            re.fullmatch(r"ev_[0-9a-f]{24}", reference) is None
            for reference in self.evidence_references
        ):
            raise ValueError("invalid evidence reference")
        if self.status in {"supported", "refuted"} and not self.evidence_references:
            raise ValueError("supported or refuted hypotheses require evidence")
        return self


class NativeEvidenceFailure(ClosedModel):
    status: Literal["none", "failed"]
    category: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=500)


class NativeEvidenceEnvelope(ClosedModel):
    reference: str = Field(pattern=r"^ev_[0-9a-f]{24}$")
    facts: dict[str, Any]
    scope: CurrentStoreScope
    period: EvidencePeriodResult
    group_by: EvidenceGroup | None = None
    filters: EvidenceFilters | None = None
    extreme: Literal["highest", "lowest"] | None = None
    unit: Literal["EUR", "day", "car", "EUR/car", "EUR/operating_day", "unknown"]
    source: list[Literal["store_daily_records", "settlement_records"]]
    queried_at: datetime
    data_version: str = Field(min_length=1, max_length=100)
    coverage: EvidenceCoverage
    completeness: EvidenceCompleteness | None = None
    limitations: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool
    failure: NativeEvidenceFailure


class NativeToolResult(ClosedModel):
    call_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    evidence: NativeEvidenceEnvelope


class NativeTranscriptItem(ClosedModel):
    message: ModelMessage | None = None
    tool_result: NativeToolResult | None = None
    hypotheses: list[NativeAnalysisHypothesis] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def require_one_item(self) -> NativeTranscriptItem:
        if (self.message is None) == (self.tool_result is None):
            raise ValueError("a transcript item requires exactly one message or tool result")
        if self.hypotheses and (self.message is None or self.message.role != "assistant"):
            raise ValueError("analysis hypotheses require an assistant message")
        return self


class NativeModelTurn(ClosedModel):
    message: ModelMessage
    tool_calls: list[NativeToolCall] = Field(default_factory=list, max_length=4)
    hypotheses: list[NativeAnalysisHypothesis] = Field(default_factory=list, max_length=8)
    answer_claims: list[NativeAnswerClaim] = Field(default_factory=list, max_length=20)
    signal: Literal["continue", "end"]

    @model_validator(mode="after")
    def require_signal_shape(self) -> NativeModelTurn:
        if self.message.role != "assistant":
            raise ValueError("native model turns require an assistant message")
        if self.signal == "continue" and not self.tool_calls:
            raise ValueError("continue requires at least one tool call")
        if self.signal == "end" and self.tool_calls:
            raise ValueError("end cannot include tool calls")
        if self.signal == "continue" and self.answer_claims:
            raise ValueError("answer claims are only allowed on an ending turn")
        call_ids = [call.id for call in self.tool_calls]
        if len(call_ids) != len(set(call_ids)):
            raise ValueError("tool call ids must be unique within a turn")
        return self


class NativeModelCall(ClosedModel):
    items: list[NativeTranscriptItem]
    tools: list[NativeToolDefinition]


class NativeToolModel(Protocol):
    async def next_turn(
        self,
        items: Sequence[NativeTranscriptItem],
        *,
        tools: Sequence[NativeToolDefinition],
    ) -> NativeModelTurn: ...


class NativeEvidenceCollector(Protocol):
    async def collect(
        self,
        plan: EvidencePlan,
        context: RuntimeContext,
    ) -> object: ...


class NativeToolScopeResolver(Protocol):
    async def refresh(self, context: RuntimeContext) -> RuntimeContext: ...


@dataclass(frozen=True)
class NativeToolSpec:
    metric: EvidenceMetric
    result_types: tuple[type[BaseModel], ...]
    arguments_type: type[MonthlyTotalRevenueArguments]
    description: str
    sources: tuple[Literal["store_daily_records", "settlement_records"], ...]
    unit: Literal["EUR", "day", "car", "EUR/car", "EUR/operating_day"]


NATIVE_TOOLS = {
    MONTHLY_TOTAL_REVENUE_TOOL: NativeToolSpec(
        metric=EvidenceMetric.MONTHLY_TOTAL_REVENUE,
        result_types=(MonthlyTotalRevenueResult,),
        arguments_type=MonthlyTotalRevenueArguments,
        description=(
            "查询当前受信任门店指定自然月的月度总收入，包括每日台账营业额与已确认公司结算收入。"
        ),
        sources=("store_daily_records", "settlement_records"),
        unit="EUR",
    ),
    DAILY_LEDGER_REVENUE_TOOL: NativeToolSpec(
        metric=EvidenceMetric.DAILY_LEDGER_REVENUE,
        result_types=(DailyLedgerRevenueResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询当前受信任门店指定自然月的每日台账营业额合计。",
        sources=("store_daily_records",),
        unit="EUR",
    ),
    CONFIRMED_SETTLEMENT_INCOME_TOOL: NativeToolSpec(
        metric=EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME,
        result_types=(ConfirmedSettlementIncomeResult,),
        arguments_type=MonthlyTotalRevenueArguments,
        description="查询当前受信任门店指定自然月的已确认公司结算收入。",
        sources=("settlement_records",),
        unit="EUR",
    ),
    OPERATING_DAYS_TOOL: NativeToolSpec(
        metric=EvidenceMetric.OPERATING_DAYS,
        result_types=(OperatingDaysResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询当前受信任门店指定自然月的经营日数量。",
        sources=("store_daily_records",),
        unit="day",
    ),
    OPERATING_DAY_AVERAGE_LEDGER_REVENUE_TOOL: NativeToolSpec(
        metric=EvidenceMetric.OPERATING_DAY_AVERAGE_LEDGER_REVENUE,
        result_types=(OperatingDayAverageLedgerRevenueResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询经营日均台账营业额；分母只包含营业和提前休息的经营日。",
        sources=("store_daily_records",),
        unit="EUR/operating_day",
    ),
    MONTHLY_DAILY_AVERAGE_INCOME_TOOL: NativeToolSpec(
        metric=EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME,
        result_types=(MonthlyDailyAverageIncomeResult,),
        arguments_type=MonthlyTotalRevenueArguments,
        description="查询指定自然月的月度日均收入，包含已确认公司结算收入。",
        sources=("store_daily_records", "settlement_records"),
        unit="EUR/operating_day",
    ),
    WASH_COUNT_TOOL: NativeToolSpec(
        metric=EvidenceMetric.WASH_COUNT,
        result_types=(WashCountResult,),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询洗车数量及其经营日数据覆盖；缺失洗车数量不会按零计算。",
        sources=("store_daily_records",),
        unit="car",
    ),
    AVERAGE_REVENUE_PER_CAR_TOOL: NativeToolSpec(
        metric=EvidenceMetric.AVERAGE_REVENUE_PER_CAR,
        result_types=(AverageRevenuePerCarResult,),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询平均每车收入及其一致的营业额、洗车数量和覆盖范围。",
        sources=("store_daily_records",),
        unit="EUR/car",
    ),
    INCOME_CATEGORY_AMOUNT_TOOL: NativeToolSpec(
        metric=EvidenceMetric.INCOME_CATEGORY_AMOUNT,
        result_types=(CategoryAmountResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询动态收入分类金额，支持批准的分组和筛选。",
        sources=("store_daily_records",),
        unit="EUR",
    ),
    OTHER_DATA_AMOUNT_TOOL: NativeToolSpec(
        metric=EvidenceMetric.OTHER_DATA_AMOUNT,
        result_types=(CategoryAmountResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询不计入总营业额的其他数据，支持批准的分组和筛选。",
        sources=("store_daily_records",),
        unit="EUR",
    ),
    DAILY_LEDGER_REVENUE_EXTREME_TOOL: NativeToolSpec(
        metric=EvidenceMetric.DAILY_LEDGER_REVENUE,
        result_types=(DailyLedgerExtremeResult,),
        arguments_type=DailyLedgerRevenueExtremeArguments,
        description="查询经营日每日台账营业额的最高或最低日期，支持批准的筛选。",
        sources=("store_daily_records",),
        unit="EUR",
    ),
}


class FakeNativeToolModel:
    """Scriptable native-tool model used by high-level acceptance tests."""

    def __init__(
        self,
        *,
        turns: Iterable[NativeModelTurn | dict[str, Any]],
        before_turn: Callable[[], None] | None = None,
    ) -> None:
        self._turns = list(turns)
        self._before_turn = before_turn
        self.calls: list[NativeModelCall] = []

    async def next_turn(
        self,
        items: Sequence[NativeTranscriptItem],
        *,
        tools: Sequence[NativeToolDefinition],
    ) -> NativeModelTurn:
        if self._before_turn is not None:
            self._before_turn()
        self.calls.append(NativeModelCall(items=list(items), tools=list(tools)))
        if not self._turns:
            raise RuntimeError("no scripted native model turn remains")
        scripted = self._turns.pop(0)
        return (
            scripted
            if isinstance(scripted, NativeModelTurn)
            else NativeModelTurn.model_validate(scripted)
        )


class NativeToolAgentService:
    """Provider-neutral loop for evidence-driven, bounded investigations."""

    def __init__(
        self,
        *,
        model: NativeToolModel,
        evidence_collector: NativeEvidenceCollector,
        scope_resolver: NativeToolScopeResolver,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.model = model
        self.evidence_collector = evidence_collector
        self.scope_resolver = scope_resolver
        self.now = now
        self.tool_registry = tuple(
            NativeToolRegistration(
                definition=NativeToolDefinition(
                    name=name,
                    description=spec.description,
                    input_schema=spec.arguments_type.model_json_schema(),
                ),
                # Historical evidence remains available when optional store
                # data-entry features are disabled.
                required_features=frozenset(),
            )
            for name, spec in NATIVE_TOOLS.items()
        )

    async def run(
        self,
        context: RuntimeContext,
        state: ConversationState,
        recent_messages: list[ModelMessage],
    ) -> AgentRunResult:
        if not _available_tools(context, self.tool_registry):
            raise NativeToolAccessDenied("native tools are not available for this runtime scope")
        catalog_context = await self.scope_resolver.refresh(context)
        if (
            catalog_context.user_id != context.user_id
            or catalog_context.store_id != context.store_id
        ):
            raise NativeToolAccessDenied("native tools are not available for this runtime scope")
        tools = _available_tools(catalog_context, self.tool_registry)
        if not tools:
            raise NativeToolAccessDenied("native tools are not available for this runtime scope")
        trusted_period = _explicit_calendar_month(recent_messages)
        if trusted_period is None:
            return AgentRunResult(
                turn=TurnResult(route="clarify", content=EXACT_MONTH_CLARIFICATION),
                state=state.model_copy(
                    update={"pending_clarifications": [EXACT_MONTH_CLARIFICATION]}
                ),
            )
        items = [NativeTranscriptItem(message=message) for message in recent_messages]
        collected: list[EvidenceBundle] = []
        evidence_by_reference: dict[str, EvidenceBundle] = {}
        tool_call_count = 0
        for round_number in range(MAX_NATIVE_TOOL_ROUNDS):
            if round_number:
                catalog_context = await self.scope_resolver.refresh(catalog_context)
                if (
                    catalog_context.user_id != context.user_id
                    or catalog_context.store_id != context.store_id
                ):
                    raise NativeToolAccessDenied(
                        "native tools are not available for this runtime scope"
                    )
                tools = _available_tools(catalog_context, self.tool_registry)
                if not tools:
                    raise NativeToolAccessDenied(
                        "native tools are not available for this runtime scope"
                    )
            turn = await self.model.next_turn(items, tools=tools)
            hypothesis_error = _hypothesis_reference_error(turn.hypotheses, items)
            if hypothesis_error is not None:
                items.append(
                    NativeTranscriptItem(
                        message=ModelMessage(role="system", content=hypothesis_error)
                    )
                )
                continue
            items.append(
                NativeTranscriptItem(
                    message=turn.message,
                    hypotheses=turn.hypotheses,
                )
            )
            if turn.signal == "end":
                if not answer_is_grounded(
                    turn.message.content,
                    collected,
                    turn.answer_claims,
                    evidence_by_reference,
                ):
                    return AgentRunResult(
                        turn=TurnResult(
                            route="safe_failure",
                            content=ANSWER_EVIDENCE_FAILURE_MESSAGE,
                        ),
                        state=state,
                    )
                return _agent_result(
                    state,
                    collected,
                    content=turn.message.content,
                )
            if tool_call_count + len(turn.tool_calls) > MAX_NATIVE_TOOL_CALLS:
                return _agent_result(
                    state,
                    collected,
                    content=INVESTIGATION_LIMIT_MESSAGE,
                )
            outcomes = await asyncio.gather(
                *(
                    self._execute(
                        tool_call,
                        catalog_context,
                        trusted_period=trusted_period,
                    )
                    for tool_call in turn.tool_calls
                )
            )
            tool_call_count += len(turn.tool_calls)
            for tool_result, new_evidence in outcomes:
                if new_evidence is not None:
                    collected.append(new_evidence)
                    evidence_by_reference[tool_result.evidence.reference] = new_evidence
                items.append(NativeTranscriptItem(tool_result=tool_result))
        return _agent_result(
            state,
            collected,
            content=INVESTIGATION_LIMIT_MESSAGE,
        )

    async def _execute(
        self,
        call: NativeToolCall,
        context: RuntimeContext,
        *,
        trusted_period: MonthlyTotalRevenueArguments,
    ) -> tuple[NativeToolResult, EvidenceBundle | None]:
        tool_spec = NATIVE_TOOLS.get(call.name)
        if tool_spec is None or call.name not in {
            tool.name for tool in _available_tools(context, self.tool_registry)
        }:
            raise NativeToolAccessDenied("native tool call is not authorized")
        try:
            arguments = tool_spec.arguments_type.model_validate(call.arguments)
        except ValidationError as error:
            raise NativeToolAccessDenied("native tool call is not authorized") from error
        fresh_context = await self.scope_resolver.refresh(context)
        if (
            fresh_context.user_id != context.user_id
            or fresh_context.store_id != context.store_id
            or call.name
            not in {tool.name for tool in _available_tools(fresh_context, self.tool_registry)}
        ):
            raise NativeToolAccessDenied("native tool call is not authorized")
        if arguments.year != trusted_period.year or arguments.month != trusted_period.month:
            return (
                _failed_tool_result(
                    call,
                    fresh_context,
                    trusted_period,
                    self.now(),
                    tool_spec=tool_spec,
                    category="period_scope_mismatch",
                    message="工具期间与用户确认的自然月不一致",
                ),
                None,
            )
        request: dict[str, Any] = {
            "kind": "business_metrics",
            "metric": tool_spec.metric,
            "period": {
                "kind": "calendar_month",
                "year": arguments.year,
                "month": arguments.month,
            },
        }
        for field in ("group_by", "filters", "extreme"):
            value = getattr(arguments, field, None)
            if value is not None:
                request[field] = value
        try:
            plan = EvidencePlan.model_validate({"requests": [request]})
        except ValidationError as error:
            raise NativeToolAccessDenied("native tool call is not authorized") from error
        try:
            evidence = await self.evidence_collector.collect(plan, fresh_context)
        except NativeToolAccessDenied:
            raise
        except Exception:
            return (
                _failed_tool_result(
                    call,
                    fresh_context,
                    arguments,
                    self.now(),
                    tool_spec=tool_spec,
                ),
                None,
            )
        if (
            not isinstance(evidence, EvidenceBundle)
            or evidence.metric != tool_spec.metric
            or not isinstance(evidence.result, tool_spec.result_types)
            or evidence.group_by != getattr(arguments, "group_by", None)
            or evidence.filters != getattr(arguments, "filters", None)
            or evidence.extreme != getattr(arguments, "extreme", None)
        ):
            return (
                _failed_tool_result(
                    call,
                    fresh_context,
                    arguments,
                    self.now(),
                    tool_spec=tool_spec,
                ),
                None,
            )
        envelope = _native_envelope(evidence, queried_at=self.now())
        return (
            NativeToolResult(
                call_id=call.id,
                name=call.name,
                evidence=envelope,
            ),
            evidence,
        )


def _available_tools(
    context: RuntimeContext,
    registrations: Sequence[NativeToolRegistration],
) -> tuple[NativeToolDefinition, ...]:
    return tuple(
        registration.definition
        for registration in registrations
        if registration.is_available(context)
    )


def _native_envelope(
    evidence: EvidenceBundle,
    *,
    queried_at: datetime,
) -> NativeEvidenceEnvelope:
    facts = evidence.result.model_dump(mode="json")
    version_payload: dict[str, Any] = {
        "scope": evidence.current_store.model_dump(mode="json"),
        "period": evidence.period.model_dump(mode="json"),
        "calculation_version": evidence.calculation_version,
        "facts": facts,
        "coverage": evidence.coverage.model_dump(mode="json"),
    }
    if evidence.group_by is not None:
        version_payload["group_by"] = evidence.group_by
    if evidence.filters is not None:
        version_payload["filters"] = evidence.filters.model_dump(mode="json")
    if evidence.extreme is not None:
        version_payload["extreme"] = evidence.extreme
    if evidence.completeness is not None:
        version_payload["completeness"] = evidence.completeness.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    limitations = list(evidence.warnings)
    if evidence.completeness is not None and evidence.completeness.unrecorded_dates:
        limitations.append(f"{len(evidence.completeness.unrecorded_dates)} 个日期没有每日台账记录")
    tool_spec = NATIVE_TOOLS[evidence.metric.value]
    return NativeEvidenceEnvelope(
        reference=f"ev_{digest[:24]}",
        facts=facts,
        scope=evidence.current_store,
        period=evidence.period,
        group_by=evidence.group_by,
        filters=evidence.filters,
        extreme=evidence.extreme,
        unit=tool_spec.unit,
        source=list(tool_spec.sources),
        queried_at=queried_at,
        data_version=f"sha256:{digest}",
        coverage=evidence.coverage,
        completeness=evidence.completeness,
        limitations=limitations[:20],
        truncated=evidence.truncated,
        failure=NativeEvidenceFailure(status="none"),
    )


def _failed_tool_result(
    call: NativeToolCall,
    context: RuntimeContext,
    arguments: MonthlyTotalRevenueArguments,
    queried_at: datetime,
    *,
    tool_spec: NativeToolSpec | None,
    category: str = "business_query_unavailable",
    message: str = "经营查询暂时不可用",
) -> NativeToolResult:
    start = date(arguments.year, arguments.month, 1)
    end = date(arguments.year, arguments.month, monthrange(arguments.year, arguments.month)[1])
    digest = hashlib.sha256(
        f"{context.store_id}:{start.isoformat()}:{end.isoformat()}:failed".encode()
    ).hexdigest()
    return NativeToolResult(
        call_id=call.id,
        name=call.name,
        evidence=NativeEvidenceEnvelope(
            reference=f"ev_{digest[:24]}",
            facts={},
            scope=CurrentStoreScope(id=context.store_id),
            period=EvidencePeriodResult(start=start, end=end),
            group_by=None,
            filters=None,
            extreme=None,
            unit=tool_spec.unit if tool_spec is not None else "unknown",
            source=list(tool_spec.sources) if tool_spec is not None else [],
            queried_at=queried_at,
            data_version=f"unavailable:{digest}",
            coverage=EvidenceCoverage(
                calendar_dates=(end - start).days + 1,
                recorded_dates=0,
            ),
            completeness=None,
            limitations=["经营查询暂时失败；未返回任何经营事实"],
            truncated=False,
            failure=NativeEvidenceFailure(
                status="failed",
                category=category,
                message=message,
            ),
        ),
    )


def _hypothesis_reference_error(
    hypotheses: Sequence[NativeAnalysisHypothesis],
    items: Sequence[NativeTranscriptItem],
) -> str | None:
    known_references = {
        item.tool_result.evidence.reference for item in items if item.tool_result is not None
    }
    successful_references = {
        item.tool_result.evidence.reference
        for item in items
        if item.tool_result is not None and item.tool_result.evidence.failure.status == "none"
    }
    for hypothesis in hypotheses:
        references = set(hypothesis.evidence_references)
        if references - known_references:
            return "分析假设包含未知证据引用。请只引用本轮已返回的证据后继续或结束。"
        if hypothesis.status in {"supported", "refuted"} and references - successful_references:
            return "分析假设只有在成功证据支持时才能标记为支持或否定；请修正后继续或结束。"
    return None


def _agent_result(
    state: ConversationState,
    collected: Sequence[EvidenceBundle],
    *,
    content: str,
) -> AgentRunResult:
    if not collected:
        return AgentRunResult(
            turn=TurnResult(route="answer", content=content),
            state=state,
        )
    last_evidence = collected[-1]
    metric_labels = list(
        dict.fromkeys(EVIDENCE_METRIC_LABELS[evidence.metric] for evidence in collected)
    )
    return AgentRunResult(
        turn=TurnResult(route="answer", content=content),
        state=state.model_copy(
            update={
                "confirmed_period": ConfirmedPeriod(
                    start=last_evidence.period.start,
                    end=last_evidence.period.end,
                ),
                "metrics": metric_labels,
                "pending_clarifications": [],
            }
        ),
        evidence=last_evidence,
    )


def _explicit_calendar_month(
    messages: Sequence[ModelMessage],
) -> MonthlyTotalRevenueArguments | None:
    user_message = next(
        (message.content for message in reversed(messages) if message.role == "user"),
        "",
    )
    match = EXPLICIT_CALENDAR_MONTH.search(user_message)
    if match is None:
        return None
    return MonthlyTotalRevenueArguments(
        year=int(match.group("year")),
        month=int(match.group("month")),
    )
