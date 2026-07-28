from __future__ import annotations

import asyncio
import hashlib
import json
import re
from calendar import monthrange
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Literal, Protocol, TypeAlias, TypeVar
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pydantic import BaseModel, Field, ValidationError, model_validator

from app.agent.answer_grounding import (
    GroundedEvidence,
    NativeAnswerClaim,
    answer_contains_operating_claim,
    answer_is_grounded,
)
from app.agent.conversation import (
    AgentRunResult,
    ConfirmedPeriod,
    ConversationAnalysisHypothesis,
    ConversationEvidenceReference,
    ConversationState,
)
from app.agent.evidence_calculation import (
    CalculationUnit,
    CannotCalculateReason,
    EvidenceCalculationInput,
    EvidenceCalculationRequest,
    EvidenceCalculationResult,
    calculate_evidence,
)
from app.agent.contracts import (
    CurrentStoreScope,
    AverageRevenuePerCarResult,
    CategoryAmountResult,
    ClosedModel,
    DailyLedgerRevenueResult,
    DailyLedgerDrilldownResult,
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
    MAX_DAILY_LEDGER_DRILLDOWN_DATES,
    MessageRole,
    ModelMessage,
    MonthlyTotalRevenueResult,
    MonthlyDailyAverageIncomeResult,
    OperatingDayAverageLedgerRevenueResult,
    OperatingDaysResult,
    OpenBusinessRecordsAction,
    SETTLEMENT_DETAILS_LABEL,
    SettlementDetailsEvidenceBundle,
    SettlementDetailsQueryScope,
    SettlementDetailsResult,
    WashCountResult,
    TurnResult,
)
from app.agent.runtime import RuntimeContext
from app.agent.system_knowledge import is_system_help_request, search_system_knowledge

NativeCollectedEvidence: TypeAlias = EvidenceBundle | SettlementDetailsEvidenceBundle

MONTHLY_TOTAL_REVENUE_TOOL = "monthly_total_revenue"
DAILY_LEDGER_REVENUE_TOOL = "daily_ledger_revenue"
CONFIRMED_SETTLEMENT_INCOME_TOOL = "confirmed_settlement_income"
SETTLEMENT_DETAILS_TOOL = "settlement_details"
OPERATING_DAYS_TOOL = "operating_days"
OPERATING_DAY_AVERAGE_LEDGER_REVENUE_TOOL = "operating_day_average_ledger_revenue"
MONTHLY_DAILY_AVERAGE_INCOME_TOOL = "monthly_daily_average_income"
WASH_COUNT_TOOL = "wash_count"
AVERAGE_REVENUE_PER_CAR_TOOL = "average_revenue_per_car"
INCOME_CATEGORY_AMOUNT_TOOL = "income_category_amount"
OTHER_DATA_AMOUNT_TOOL = "other_data_amount"
DAILY_LEDGER_REVENUE_EXTREME_TOOL = "daily_ledger_revenue_extreme"
SEARCH_SYSTEM_KNOWLEDGE_TOOL = "search_system_knowledge"
OPEN_BUSINESS_RECORDS_TOOL = "open_business_records"
DAILY_LEDGER_DETAILS_TOOL = "daily_ledger_details"
EVIDENCE_CALCULATION_TOOL = "evidence_calculation"
MAX_NATIVE_TOOL_ROUNDS = 4
MAX_NATIVE_TOOL_CALLS = 8
INVESTIGATION_LIMIT_MESSAGE = "调查已达到本轮资源上限；以下结论仅基于已返回的证据。"
ANSWER_EVIDENCE_FAILURE_MESSAGE = "回答中的关键经营声明缺少本轮有效证据支持，请缩小范围后重试。"
EXPLICIT_CALENDAR_MONTH = re.compile(
    r"(?P<year>20\d{2}|21\d{2}|2200)\s*年\s*(?P<month>1[0-2]|0?[1-9])\s*月"
)
EXACT_MONTH_CLARIFICATION = "请提供要查询的准确自然月，例如“2026 年 7 月”。"
CAPABILITY_BOUNDARY_MESSAGE = (
    "我专注于 AutoLava 使用、当前门店经营分析和证据支持的经营建议。"
    "你可以问我产品操作或当前门店问题。"
)


class NativeToolAccessDenied(RuntimeError):
    """A non-retryable authorization or tool-contract failure."""


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


class DailyLedgerDetailsArguments(MonthlyTotalRevenueArguments):
    dates: list[date] = Field(
        min_length=1,
        max_length=MAX_DAILY_LEDGER_DRILLDOWN_DATES,
    )

    @model_validator(mode="after")
    def require_unique_dates_in_month(self) -> "DailyLedgerDetailsArguments":
        if len(self.dates) != len(set(self.dates)):
            raise ValueError("daily ledger detail dates must be unique")
        if any((value.year, value.month) != (self.year, self.month) for value in self.dates):
            raise ValueError("daily ledger detail dates must stay inside the requested month")
        return self


class SettlementDetailsArguments(MonthlyTotalRevenueArguments):
    status: Literal["pending", "confirmed"] | None = None
    company_name: str | None = Field(default=None, min_length=1, max_length=120)


class SearchSystemKnowledgeArguments(ClosedModel):
    pass


class OpenBusinessRecordsArguments(ClosedModel):
    start_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")
    end_month: str = Field(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")


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


NativeAnalysisHypothesis: TypeAlias = ConversationAnalysisHypothesis


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
    selected_dates: list[date] | None = None
    settlement_query_scope: SettlementDetailsQueryScope | None = None
    unit: Literal[
        "EUR",
        "day",
        "car",
        "EUR/car",
        "EUR/operating_day",
        "mixed",
        "unknown",
    ]
    source: list[
        Literal[
            "store_daily_records",
            "settlement_records",
            "system_knowledge",
            "navigation_registry",
        ]
    ]
    queried_at: datetime
    data_version: str = Field(min_length=1, max_length=100)
    coverage: EvidenceCoverage
    completeness: EvidenceCompleteness | None = None
    limitations: list[str] = Field(default_factory=list, max_length=20)
    truncated: bool
    failure: NativeEvidenceFailure


class NativeCalculationEnvelope(ClosedModel):
    reference: str = Field(pattern=r"^ev_[0-9a-f]{24}$")
    formula: str | None
    input_evidence_references: list[str] = Field(min_length=2, max_length=8)
    input_data_versions: list[str] = Field(max_length=8)
    exact_result: Decimal | None
    unit: CalculationUnit | None
    cannot_calculate_reason: CannotCalculateReason | None
    scope: CurrentStoreScope
    period: EvidencePeriodResult
    calculated_at: datetime
    data_version: str = Field(min_length=1, max_length=100)
    failure: NativeEvidenceFailure

    @model_validator(mode="after")
    def require_result_or_reason(self) -> NativeCalculationEnvelope:
        succeeded = self.cannot_calculate_reason is None
        if succeeded and (
            self.formula is None
            or self.exact_result is None
            or self.unit is None
            or self.failure.status != "none"
        ):
            raise ValueError("successful evidence calculation requires an exact result")
        if not succeeded and (
            self.formula is not None
            or self.exact_result is not None
            or self.unit is not None
            or self.failure.status != "failed"
        ):
            raise ValueError("failed evidence calculation requires only a reason")
        return self


class NativeToolResult(ClosedModel):
    call_id: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    evidence: NativeEvidenceEnvelope | NativeCalculationEnvelope


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
    hypotheses: list[NativeAnalysisHypothesis] | None = Field(default=None, max_length=8)
    pending_directions: list[str] | None = Field(default=None, max_length=8)
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
    metric: EvidenceMetric | None
    result_types: tuple[type[BaseModel], ...]
    arguments_type: type[MonthlyTotalRevenueArguments]
    description: str
    sources: tuple[Literal["store_daily_records", "settlement_records"], ...]
    unit: Literal["EUR", "day", "car", "EUR/car", "EUR/operating_day", "mixed"]
    calculation_field: str | None
    request_kind: Literal[
        "business_metrics",
        "settlement_details",
        "daily_ledger_drilldown",
    ] = "business_metrics"
    include_period: bool = True
    required_features: frozenset[StoreFeatureFlag] = frozenset()


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
        calculation_field="monthly_total_revenue",
    ),
    DAILY_LEDGER_REVENUE_TOOL: NativeToolSpec(
        metric=EvidenceMetric.DAILY_LEDGER_REVENUE,
        result_types=(DailyLedgerRevenueResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询当前受信任门店指定自然月的每日台账营业额合计。",
        sources=("store_daily_records",),
        unit="EUR",
        calculation_field="daily_ledger_revenue",
    ),
    CONFIRMED_SETTLEMENT_INCOME_TOOL: NativeToolSpec(
        metric=EvidenceMetric.CONFIRMED_SETTLEMENT_INCOME,
        result_types=(ConfirmedSettlementIncomeResult,),
        arguments_type=MonthlyTotalRevenueArguments,
        description="查询当前受信任门店指定自然月的已确认公司结算收入。",
        sources=("settlement_records",),
        unit="EUR",
        calculation_field="confirmed_settlement_income",
    ),
    SETTLEMENT_DETAILS_TOOL: NativeToolSpec(
        metric=None,
        result_types=(SettlementDetailsResult,),
        arguments_type=SettlementDetailsArguments,
        description=(
            "查询当前受信任门店指定自然月的结算公司、待到账或已确认开票记录；"
            "公司结算只按开票月份归属，没有日粒度。"
        ),
        sources=("settlement_records",),
        unit="EUR",
        request_kind="settlement_details",
        calculation_field=None,
        required_features=frozenset({"company_settlement_enabled"}),
    ),
    OPERATING_DAYS_TOOL: NativeToolSpec(
        metric=EvidenceMetric.OPERATING_DAYS,
        result_types=(OperatingDaysResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询当前受信任门店指定自然月的经营日数量。",
        sources=("store_daily_records",),
        unit="day",
        calculation_field="operating_days",
    ),
    OPERATING_DAY_AVERAGE_LEDGER_REVENUE_TOOL: NativeToolSpec(
        metric=EvidenceMetric.OPERATING_DAY_AVERAGE_LEDGER_REVENUE,
        result_types=(OperatingDayAverageLedgerRevenueResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询经营日均台账营业额；分母只包含营业和提前休息的经营日。",
        sources=("store_daily_records",),
        unit="EUR/operating_day",
        calculation_field="operating_day_average_ledger_revenue",
    ),
    MONTHLY_DAILY_AVERAGE_INCOME_TOOL: NativeToolSpec(
        metric=EvidenceMetric.MONTHLY_DAILY_AVERAGE_INCOME,
        result_types=(MonthlyDailyAverageIncomeResult,),
        arguments_type=MonthlyTotalRevenueArguments,
        description="查询指定自然月的月度日均收入，包含已确认公司结算收入。",
        sources=("store_daily_records", "settlement_records"),
        unit="EUR/operating_day",
        calculation_field="monthly_daily_average_income",
    ),
    WASH_COUNT_TOOL: NativeToolSpec(
        metric=EvidenceMetric.WASH_COUNT,
        result_types=(WashCountResult,),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询洗车数量及其经营日数据覆盖；缺失洗车数量不会按零计算。",
        sources=("store_daily_records",),
        unit="car",
        calculation_field="wash_count",
    ),
    AVERAGE_REVENUE_PER_CAR_TOOL: NativeToolSpec(
        metric=EvidenceMetric.AVERAGE_REVENUE_PER_CAR,
        result_types=(AverageRevenuePerCarResult,),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询平均每车收入及其一致的营业额、洗车数量和覆盖范围。",
        sources=("store_daily_records",),
        unit="EUR/car",
        calculation_field="average_revenue_per_car",
    ),
    INCOME_CATEGORY_AMOUNT_TOOL: NativeToolSpec(
        metric=EvidenceMetric.INCOME_CATEGORY_AMOUNT,
        result_types=(CategoryAmountResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询动态收入分类金额，支持批准的分组和筛选。",
        sources=("store_daily_records",),
        unit="EUR",
        calculation_field="amount",
    ),
    OTHER_DATA_AMOUNT_TOOL: NativeToolSpec(
        metric=EvidenceMetric.OTHER_DATA_AMOUNT,
        result_types=(CategoryAmountResult, GroupedMetricResult),
        arguments_type=ComposableBusinessMetricArguments,
        description="查询不计入总营业额的其他数据，支持批准的分组和筛选。",
        sources=("store_daily_records",),
        unit="EUR",
        calculation_field="amount",
    ),
    DAILY_LEDGER_REVENUE_EXTREME_TOOL: NativeToolSpec(
        metric=EvidenceMetric.DAILY_LEDGER_REVENUE,
        result_types=(DailyLedgerExtremeResult,),
        arguments_type=DailyLedgerRevenueExtremeArguments,
        description="查询经营日每日台账营业额的最高或最低日期，支持批准的筛选。",
        sources=("store_daily_records",),
        unit="EUR",
        calculation_field="daily_ledger_revenue",
    ),
    DAILY_LEDGER_DETAILS_TOOL: NativeToolSpec(
        metric=EvidenceMetric.DAILY_LEDGER,
        result_types=(DailyLedgerDrilldownResult,),
        arguments_type=DailyLedgerDetailsArguments,
        description=(
            "按聚合线索钻取当前受信任门店指定自然月内的受控日期集合；"
            "返回每日台账事实、原始事件和缺失字段，不用于无条件读取整月明细。"
        ),
        sources=("store_daily_records",),
        unit="mixed",
        calculation_field=None,
        request_kind="daily_ledger_drilldown",
        include_period=False,
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
                required_features=spec.required_features,
            )
            for name, spec in NATIVE_TOOLS.items()
        ) + (
            NativeToolRegistration(
                definition=NativeToolDefinition(
                    name=SEARCH_SYSTEM_KNOWLEDGE_TOOL,
                    description=(
                        "搜索批准的 AutoLava 只读产品文档、领域语言、操作说明和能力描述。"
                        "不接受路径、网址或任意文件。"
                    ),
                    input_schema=SearchSystemKnowledgeArguments.model_json_schema(),
                ),
                required_features=frozenset(),
            ),
            NativeToolRegistration(
                definition=NativeToolDefinition(
                    name=OPEN_BUSINESS_RECORDS_TOOL,
                    description=(
                        "准备打开已注册的营业记录只读筛选视图。只接受受控月份范围，"
                        "不接受网址、写入、导入导出或备份参数。"
                    ),
                    input_schema=OpenBusinessRecordsArguments.model_json_schema(),
                ),
                required_features=frozenset(),
            ),
            NativeToolRegistration(
                definition=NativeToolDefinition(
                    name=EVIDENCE_CALCULATION_TOOL,
                    description=(
                        "只使用本轮已返回的证据引用执行固定精确计算；"
                        "不能查询新经营数据或指定身份、门店、字段、SQL、表或任意表达式。"
                    ),
                    input_schema=EvidenceCalculationRequest.model_json_schema(),
                ),
                required_features=frozenset(),
            ),
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
        trusted_period = _trusted_period(state, recent_messages)
        items = [
            NativeTranscriptItem(message=_investigation_context_message(state)),
            *(NativeTranscriptItem(message=message) for message in recent_messages),
        ]
        collected: list[NativeCollectedEvidence] = []
        calculations: list[NativeCalculationEnvelope] = []
        evidence_by_reference: dict[str, GroundedEvidence] = {}
        calculation_inputs: dict[str, EvidenceCalculationInput] = {}
        evidence_references = list(state.evidence_references)
        hypotheses = list(state.analysis_hypotheses)
        pending_directions = list(state.pending_directions)
        contextual_results: list[NativeToolResult] = []
        selected_action: OpenBusinessRecordsAction | None = None
        period_confirmation_required = False
        pending_period_candidate: MonthlyTotalRevenueArguments | None = None
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
            hypothesis_error = _hypothesis_reference_error(turn.hypotheses or [], items)
            if hypothesis_error is not None:
                items.append(
                    NativeTranscriptItem(
                        message=ModelMessage(role=MessageRole.SYSTEM, content=hypothesis_error)
                    )
                )
                continue
            items.append(
                NativeTranscriptItem(
                    message=turn.message,
                    hypotheses=turn.hypotheses or [],
                )
            )
            if turn.hypotheses is not None:
                hypotheses = list(turn.hypotheses)
            if turn.pending_directions is not None:
                pending_directions = turn.pending_directions
            if turn.signal == "end":
                if period_confirmation_required:
                    clarification = (
                        _period_confirmation_prompt(pending_period_candidate)
                        if pending_period_candidate is not None
                        else EXACT_MONTH_CLARIFICATION
                    )
                    return AgentRunResult(
                        turn=TurnResult(
                            route="clarify",
                            content=clarification,
                        ),
                        state=state.model_copy(
                            update={
                                "pending_clarifications": [clarification],
                            }
                        ),
                    )
                if (collected or calculations) and not answer_is_grounded(
                    turn.message.content,
                    [*collected, *calculations],
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
                if not collected and not contextual_results:
                    if answer_is_grounded(
                        turn.message.content,
                        [*collected, *calculations],
                        turn.answer_claims,
                        evidence_by_reference,
                    ):
                        return _agent_result(
                            state,
                            collected,
                            content=turn.message.content,
                        )
                    if answer_contains_operating_claim(turn.message.content):
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
                        content=CAPABILITY_BOUNDARY_MESSAGE,
                    )
                if not collected:
                    if selected_action is not None:
                        return _agent_result(
                            state,
                            collected,
                            content=_navigation_confirmation(selected_action),
                            action=selected_action,
                        )
                    knowledge_answer = _approved_knowledge_answer(contextual_results)
                    if knowledge_answer is not None:
                        return _agent_result(
                            state,
                            collected,
                            content=knowledge_answer,
                        )
                    return _agent_result(
                        state,
                        collected,
                        content=CAPABILITY_BOUNDARY_MESSAGE,
                    )
                return _agent_result(
                    state,
                    collected,
                    evidence_references=evidence_references,
                    hypotheses=hypotheses,
                    pending_directions=pending_directions,
                    content=turn.message.content,
                    action=selected_action,
                )
            if tool_call_count + len(turn.tool_calls) > MAX_NATIVE_TOOL_CALLS:
                return _agent_result(
                    state,
                    collected,
                    evidence_references=evidence_references,
                    hypotheses=hypotheses,
                    pending_directions=pending_directions,
                    content=INVESTIGATION_LIMIT_MESSAGE,
                )
            outcomes = await asyncio.gather(
                *(
                    self._execute(
                        tool_call,
                        catalog_context,
                        trusted_period=trusted_period,
                        recent_messages=recent_messages,
                        calculation_inputs=calculation_inputs,
                    )
                    for tool_call in turn.tool_calls
                )
            )
            tool_call_count += len(turn.tool_calls)
            round_actions = [action for _, _, action in outcomes if action is not None]
            if len(round_actions) > 1 or (selected_action is not None and round_actions):
                raise NativeToolAccessDenied("native tool call is not authorized")
            if round_actions and _navigation_action_is_authorized(
                recent_messages,
                round_actions[0],
            ):
                selected_action = round_actions[0]
            for tool_result, new_evidence, action in outcomes:
                if tool_result.evidence.failure.category == "period_confirmation_required":
                    period_confirmation_required = True
                    candidate = MonthlyTotalRevenueArguments(
                        year=tool_result.evidence.period.start.year,
                        month=tool_result.evidence.period.start.month,
                    )
                    if pending_period_candidate is None:
                        pending_period_candidate = candidate
                    elif pending_period_candidate != candidate:
                        pending_period_candidate = None
                if new_evidence is not None:
                    collected.append(new_evidence)
                    evidence_by_reference[tool_result.evidence.reference] = new_evidence
                    assert isinstance(tool_result.evidence, NativeEvidenceEnvelope)
                    evidence_references.append(
                        ConversationEvidenceReference(
                            reference=tool_result.evidence.reference,
                            source=tool_result.evidence.source,
                            queried_at=tool_result.evidence.queried_at,
                            data_version=tool_result.evidence.data_version,
                            period=ConfirmedPeriod(
                                start=tool_result.evidence.period.start,
                                end=tool_result.evidence.period.end,
                            ),
                        )
                    )
                    evidence_references = evidence_references[-50:]
                elif tool_result.evidence.failure.status == "none" and (
                    isinstance(tool_result.evidence, NativeCalculationEnvelope)
                ):
                    calculations.append(tool_result.evidence)
                    evidence_by_reference[tool_result.evidence.reference] = tool_result.evidence
                elif tool_result.evidence.failure.status == "none" and (
                    action is None or action == selected_action
                ):
                    contextual_results.append(tool_result)
                if isinstance(tool_result.evidence, NativeEvidenceEnvelope):
                    tool_spec = NATIVE_TOOLS.get(tool_result.name)
                    fact_name = tool_spec.calculation_field if tool_spec is not None else None
                    raw_value = (
                        tool_result.evidence.facts.get(fact_name) if fact_name is not None else None
                    )
                    primary_value = (
                        Decimal(str(raw_value))
                        if isinstance(raw_value, (int, float, Decimal))
                        and not isinstance(raw_value, bool)
                        else None
                    )
                    calculation_inputs[tool_result.evidence.reference] = EvidenceCalculationInput(
                        reference=tool_result.evidence.reference,
                        primary_value=primary_value,
                        unit=(
                            tool_spec.unit
                            if tool_spec is not None and tool_spec.calculation_field is not None
                            else None
                        ),
                        store_id=tool_result.evidence.scope.id,
                        queried_at=tool_result.evidence.queried_at,
                        data_version=tool_result.evidence.data_version,
                        available=(
                            tool_result.evidence.failure.status == "none"
                            and primary_value is not None
                        ),
                    )
                items.append(NativeTranscriptItem(tool_result=tool_result))
        return _agent_result(
            state,
            collected,
            evidence_references=evidence_references,
            hypotheses=hypotheses,
            pending_directions=pending_directions,
            content=INVESTIGATION_LIMIT_MESSAGE,
            action=selected_action,
        )

    async def _execute(
        self,
        call: NativeToolCall,
        context: RuntimeContext,
        *,
        trusted_period: MonthlyTotalRevenueArguments | None,
        recent_messages: Sequence[ModelMessage],
        calculation_inputs: dict[str, EvidenceCalculationInput],
    ) -> tuple[
        NativeToolResult,
        NativeCollectedEvidence | None,
        OpenBusinessRecordsAction | None,
    ]:
        if call.name == SEARCH_SYSTEM_KNOWLEDGE_TOOL:
            return await self._search_system_knowledge(
                call,
                context,
                recent_messages,
            )
        if call.name == OPEN_BUSINESS_RECORDS_TOOL:
            return await self._open_business_records(call, context)
        if call.name == EVIDENCE_CALCULATION_TOOL:
            if trusted_period is None:
                raise NativeToolAccessDenied("native tool call is not authorized")
            try:
                calculation_request = EvidenceCalculationRequest.model_validate(call.arguments)
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
            calculated_at = self.now()
            calculation = calculate_evidence(
                calculation_request,
                calculation_inputs,
                current_store_id=fresh_context.store_id,
                now=calculated_at,
            )
            calculation_envelope = _calculation_envelope(
                calculation,
                request=calculation_request,
                context=fresh_context,
                period=EvidencePeriodResult(
                    start=date(trusted_period.year, trusted_period.month, 1),
                    end=date(
                        trusted_period.year,
                        trusted_period.month,
                        monthrange(trusted_period.year, trusted_period.month)[1],
                    ),
                ),
                available_evidence=calculation_inputs,
                calculated_at=calculated_at,
            )
            return (
                NativeToolResult(
                    call_id=call.id,
                    name=call.name,
                    evidence=calculation_envelope,
                ),
                None,
                None,
            )
        tool_spec = NATIVE_TOOLS.get(call.name)
        if tool_spec is None:
            raise NativeToolAccessDenied("native tool call is not authorized")
        arguments, fresh_context = await _validated_context_arguments(
            call,
            context,
            self.tool_registry,
            tool_spec.arguments_type,
            self.scope_resolver,
        )
        if trusted_period is None:
            return (
                _failed_tool_result(
                    call,
                    fresh_context,
                    arguments,
                    self.now(),
                    tool_spec=tool_spec,
                    category="period_confirmation_required",
                    message=EXACT_MONTH_CLARIFICATION,
                ),
                None,
                None,
            )
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
                None,
            )
        request: dict[str, Any] = {"kind": tool_spec.request_kind}
        if tool_spec.include_period:
            request["period"] = {
                "kind": "calendar_month",
                "year": arguments.year,
                "month": arguments.month,
            }
        if tool_spec.request_kind == "business_metrics" and tool_spec.metric is not None:
            request["metric"] = tool_spec.metric
        for field in ("group_by", "filters", "extreme", "status", "company_name", "dates"):
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
                None,
            )
        if not _evidence_matches_tool(
            evidence,
            tool_spec,
            arguments,
            store_id=fresh_context.store_id,
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
                None,
            )
        assert isinstance(evidence, (EvidenceBundle, SettlementDetailsEvidenceBundle))
        envelope = _native_envelope(evidence, tool_spec=tool_spec, queried_at=self.now())
        return (
            NativeToolResult(
                call_id=call.id,
                name=call.name,
                evidence=envelope,
            ),
            evidence,
            None,
        )

    async def _search_system_knowledge(
        self,
        call: NativeToolCall,
        context: RuntimeContext,
        recent_messages: Sequence[ModelMessage],
    ) -> tuple[NativeToolResult, None, None]:
        arguments, _ = await _validated_context_arguments(
            call,
            context,
            self.tool_registry,
            SearchSystemKnowledgeArguments,
            self.scope_resolver,
        )
        assert isinstance(arguments, SearchSystemKnowledgeArguments)
        user_question = next(
            (message.content for message in reversed(recent_messages) if message.role == "user"),
            "",
        )
        matches = (
            search_system_knowledge(user_question) if is_system_help_request(user_question) else []
        )
        facts = {
            "matches": [
                {
                    "id": entry.id,
                    "title": entry.title,
                    "content": entry.content,
                    "source_kind": "approved_system_knowledge",
                }
                for entry in matches
            ]
        }
        return (
            _context_tool_result(
                call,
                context,
                facts=facts,
                source="system_knowledge",
                queried_at=self.now(),
            ),
            None,
            None,
        )

    async def _open_business_records(
        self,
        call: NativeToolCall,
        context: RuntimeContext,
    ) -> tuple[NativeToolResult, None, OpenBusinessRecordsAction]:
        arguments, _ = await _validated_context_arguments(
            call,
            context,
            self.tool_registry,
            OpenBusinessRecordsArguments,
            self.scope_resolver,
        )
        assert isinstance(arguments, OpenBusinessRecordsArguments)
        try:
            action = OpenBusinessRecordsAction.model_validate(
                {
                    "type": "open_business_records",
                    "start_month": arguments.start_month,
                    "end_month": arguments.end_month,
                }
            )
        except ValidationError as error:
            raise NativeToolAccessDenied("native tool call is not authorized") from error
        current_month = self.now().astimezone(ZoneInfo(context.store_timezone)).strftime("%Y-%m")
        if action.end_month > current_month:
            raise NativeToolAccessDenied("native tool call is not authorized")
        return (
            _context_tool_result(
                call,
                context,
                facts={"action": action.model_dump(mode="json")},
                source="navigation_registry",
                queried_at=self.now(),
            ),
            None,
            action,
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


ContextArguments = TypeVar("ContextArguments", bound=BaseModel)


async def _validated_context_arguments(
    call: NativeToolCall,
    context: RuntimeContext,
    registrations: Sequence[NativeToolRegistration],
    arguments_type: type[ContextArguments],
    scope_resolver: NativeToolScopeResolver,
) -> tuple[ContextArguments, RuntimeContext]:
    if call.name not in {tool.name for tool in _available_tools(context, registrations)}:
        raise NativeToolAccessDenied("native tool call is not authorized")
    try:
        arguments = arguments_type.model_validate(call.arguments)
    except ValidationError as error:
        raise NativeToolAccessDenied("native tool call is not authorized") from error
    fresh_context = await scope_resolver.refresh(context)
    if (
        fresh_context.user_id != context.user_id
        or fresh_context.store_id != context.store_id
        or call.name not in {tool.name for tool in _available_tools(fresh_context, registrations)}
    ):
        raise NativeToolAccessDenied("native tool call is not authorized")
    return arguments, fresh_context


def _context_tool_result(
    call: NativeToolCall,
    context: RuntimeContext,
    *,
    facts: dict[str, Any],
    source: Literal["system_knowledge", "navigation_registry"],
    queried_at: datetime,
) -> NativeToolResult:
    local_date = queried_at.astimezone(ZoneInfo(context.store_timezone)).date()
    digest = hashlib.sha256(
        json.dumps(
            {
                "scope": context.store_id,
                "source": source,
                "facts": facts,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    return NativeToolResult(
        call_id=call.id,
        name=call.name,
        evidence=NativeEvidenceEnvelope(
            reference=f"ev_{digest[:24]}",
            facts=facts,
            scope=CurrentStoreScope(id=context.store_id),
            period=EvidencePeriodResult(start=local_date, end=local_date),
            unit="unknown",
            source=[source],
            queried_at=queried_at,
            data_version=f"sha256:{digest}",
            coverage=EvidenceCoverage(calendar_dates=1, recorded_dates=0),
            limitations=[],
            truncated=False,
            failure=NativeEvidenceFailure(status="none"),
        ),
    )


def _native_envelope(
    evidence: NativeCollectedEvidence,
    *,
    tool_spec: NativeToolSpec,
    queried_at: datetime,
) -> NativeEvidenceEnvelope:
    facts = evidence.result.model_dump(mode="json")
    version_payload: dict[str, Any] = {
        "scope": evidence.current_store.model_dump(mode="json"),
        "period": evidence.period.model_dump(mode="json"),
        "calculation_version": evidence.calculation_version,
        "facts": facts,
    }
    if isinstance(evidence, EvidenceBundle):
        coverage = evidence.coverage
        group_by = evidence.group_by
        filters = evidence.filters
        extreme = evidence.extreme
        selected_dates = evidence.selected_dates
        completeness = evidence.completeness
        settlement_query_scope = None
        version_payload["coverage"] = coverage.model_dump(mode="json")
    else:
        coverage = EvidenceCoverage(
            calendar_dates=(evidence.period.end - evidence.period.start).days + 1,
            recorded_dates=0,
        )
        group_by = None
        filters = None
        extreme = None
        selected_dates = None
        completeness = None
        settlement_query_scope = evidence.query_scope
        version_payload["settlement_query_scope"] = settlement_query_scope.model_dump(mode="json")
    if group_by is not None:
        version_payload["group_by"] = group_by
    if filters is not None:
        version_payload["filters"] = filters.model_dump(mode="json")
    if extreme is not None:
        version_payload["extreme"] = extreme
    if selected_dates is not None:
        version_payload["selected_dates"] = [
            selected_date.isoformat() for selected_date in selected_dates
        ]
    if completeness is not None:
        version_payload["completeness"] = completeness.model_dump(mode="json")
    digest = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    limitations = list(evidence.warnings)
    settlement_grain_limit = "公司结算金额按开票月份归属，没有日粒度。"
    if (
        isinstance(evidence, SettlementDetailsEvidenceBundle)
        and settlement_grain_limit not in limitations
    ):
        limitations.append(settlement_grain_limit)
    if completeness is not None and completeness.unrecorded_dates:
        limitations.append(f"{len(completeness.unrecorded_dates)} 个日期没有每日台账记录")
    return NativeEvidenceEnvelope(
        reference=f"ev_{digest[:24]}",
        facts=facts,
        scope=evidence.current_store,
        period=evidence.period,
        group_by=group_by,
        filters=filters,
        extreme=extreme,
        selected_dates=selected_dates,
        settlement_query_scope=settlement_query_scope,
        unit=tool_spec.unit,
        source=list(tool_spec.sources),
        queried_at=queried_at,
        data_version=f"sha256:{digest}",
        coverage=coverage,
        completeness=completeness,
        limitations=limitations[:20],
        truncated=evidence.truncated,
        failure=NativeEvidenceFailure(status="none"),
    )


def _calculation_envelope(
    calculation: EvidenceCalculationResult,
    *,
    request: EvidenceCalculationRequest,
    context: RuntimeContext,
    period: EvidencePeriodResult,
    available_evidence: dict[str, EvidenceCalculationInput],
    calculated_at: datetime,
) -> NativeCalculationEnvelope:
    input_data_versions = [
        available_evidence[reference].data_version
        for reference in request.evidence_references
        if reference in available_evidence
    ]
    version_payload = {
        "scope": context.store_id,
        "period": period.model_dump(mode="json"),
        "operation": request.operation,
        "input_evidence_references": request.evidence_references,
        "input_data_versions": input_data_versions,
        "formula": calculation.formula,
        "exact_result": (
            str(calculation.exact_result) if calculation.exact_result is not None else None
        ),
        "unit": calculation.unit,
        "cannot_calculate_reason": calculation.cannot_calculate_reason,
    }
    digest = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    failed = calculation.cannot_calculate_reason is not None
    return NativeCalculationEnvelope(
        reference=f"ev_{digest[:24]}",
        formula=calculation.formula,
        input_evidence_references=request.evidence_references,
        input_data_versions=input_data_versions,
        exact_result=calculation.exact_result,
        unit=calculation.unit,
        cannot_calculate_reason=calculation.cannot_calculate_reason,
        scope=CurrentStoreScope(id=context.store_id),
        period=period,
        calculated_at=calculated_at,
        data_version=f"sha256:{digest}",
        failure=NativeEvidenceFailure(
            status="failed" if failed else "none",
            category="evidence_calculation_unavailable" if failed else None,
            message=calculation.cannot_calculate_reason if failed else None,
        ),
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
            selected_dates=None,
            settlement_query_scope=None,
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
        if hypothesis.status in {"supported", "refuted"}:
            return (
                "后端目前只能验证经营事实，不能验证证据与分析假设之间的语义关系；"
                "请把假设保持为待验证或无法确认。"
            )
    return None


def _agent_result(
    state: ConversationState,
    collected: Sequence[NativeCollectedEvidence],
    *,
    content: str,
    evidence_references: Sequence[ConversationEvidenceReference] | None = None,
    hypotheses: Sequence[ConversationAnalysisHypothesis] | None = None,
    pending_directions: Sequence[str] | None = None,
    action: OpenBusinessRecordsAction | None = None,
) -> AgentRunResult:
    resolved_evidence_references = (
        state.evidence_references if evidence_references is None else evidence_references
    )
    resolved_hypotheses = state.analysis_hypotheses if hypotheses is None else hypotheses
    resolved_pending_directions = (
        state.pending_directions if pending_directions is None else pending_directions
    )
    if not collected:
        return AgentRunResult(
            turn=TurnResult(route="answer", content=content, action=action),
            state=state.model_copy(
                update={
                    "analysis_hypotheses": list(resolved_hypotheses),
                    "pending_directions": list(resolved_pending_directions),
                }
            ),
        )
    last_evidence = collected[-1]
    metric_labels = list(dict.fromkeys(_evidence_label(evidence) for evidence in collected))
    confirmed_objects = list(dict.fromkeys([*state.confirmed_objects, *metric_labels]))
    return AgentRunResult(
        turn=TurnResult(route="answer", content=content, action=action),
        state=state.model_copy(
            update={
                "confirmed_period": ConfirmedPeriod(
                    start=last_evidence.period.start,
                    end=last_evidence.period.end,
                ),
                "confirmed_objects": confirmed_objects,
                "evidence_references": list(resolved_evidence_references),
                "analysis_hypotheses": list(resolved_hypotheses),
                "pending_directions": list(resolved_pending_directions),
                "metrics": metric_labels,
                "pending_clarifications": [],
            }
        ),
        evidence=last_evidence,
    )


def _evidence_matches_tool(
    evidence: object,
    tool_spec: NativeToolSpec,
    arguments: MonthlyTotalRevenueArguments,
    *,
    store_id: int,
) -> bool:
    if not isinstance(evidence, (EvidenceBundle, SettlementDetailsEvidenceBundle)):
        return False
    if isinstance(arguments, DailyLedgerDetailsArguments):
        return bool(
            isinstance(evidence, EvidenceBundle)
            and evidence.current_store.id == store_id
            and evidence.metric == EvidenceMetric.DAILY_LEDGER
            and isinstance(evidence.result, tool_spec.result_types)
            and evidence.selected_dates == sorted(arguments.dates)
            and evidence.period.start == min(arguments.dates)
            and evidence.period.end == max(arguments.dates)
        )
    if (
        evidence.current_store.id != store_id
        or evidence.period.start.day != 1
        or (evidence.period.start.year, evidence.period.start.month)
        != (arguments.year, arguments.month)
        or (evidence.period.end.year, evidence.period.end.month)
        != (arguments.year, arguments.month)
    ):
        return False
    if isinstance(evidence, SettlementDetailsEvidenceBundle):
        if (
            tool_spec.metric is not None
            or evidence.status != "ok"
            or not isinstance(evidence.result, tool_spec.result_types)
        ):
            return False
        company_name = getattr(arguments, "company_name", None)
        status = getattr(arguments, "status", None)
        if (
            evidence.query_scope.company_name != company_name
            or evidence.query_scope.status != status
        ):
            return False
        if company_name is not None and any(
            name.casefold() != company_name.casefold()
            for name in [
                *(company.name for company in evidence.result.companies),
                *(record.company_name for record in evidence.result.records),
            ]
        ):
            return False
        if status is not None and any(
            record.status != status for record in evidence.result.records
        ):
            return False
        return True
    return bool(
        evidence.metric == tool_spec.metric
        and isinstance(evidence.result, tool_spec.result_types)
        and evidence.group_by == getattr(arguments, "group_by", None)
        and evidence.filters == getattr(arguments, "filters", None)
        and evidence.extreme == getattr(arguments, "extreme", None)
    )


def _evidence_label(evidence: NativeCollectedEvidence) -> str:
    if isinstance(evidence, SettlementDetailsEvidenceBundle):
        return SETTLEMENT_DETAILS_LABEL
    return EVIDENCE_METRIC_LABELS[evidence.metric]


def _explicit_calendar_month(
    messages: Sequence[ModelMessage],
    state: ConversationState,
) -> MonthlyTotalRevenueArguments | None:
    user_message = next(
        (message.content for message in reversed(messages) if message.role == "user"),
        "",
    )
    match = EXPLICIT_CALENDAR_MONTH.search(user_message)
    if (
        match is None
        and re.fullmatch(r"\s*(?:确认|是|对|可以|继续|没错|好的|好)\s*[。.!！]?\s*", user_message)
        and state.pending_clarifications
    ):
        match = next(
            (
                candidate
                for clarification in reversed(state.pending_clarifications)
                if (candidate := EXPLICIT_CALENDAR_MONTH.search(clarification)) is not None
            ),
            None,
        )
    if match is None:
        return None
    return MonthlyTotalRevenueArguments(
        year=int(match.group("year")),
        month=int(match.group("month")),
    )


def _period_confirmation_prompt(arguments: MonthlyTotalRevenueArguments) -> str:
    start = date(arguments.year, arguments.month, 1)
    end = date(
        arguments.year,
        arguments.month,
        monthrange(arguments.year, arguments.month)[1],
    )
    return (
        f"我推定查询期间为 {arguments.year} 年 {arguments.month} 月"
        f"（{start.isoformat()} 至 {end.isoformat()}）。请确认是否按此期间继续。"
    )


_NAVIGATION_INTENT = re.compile(r"打开|带我去|跳转|查看")


def _navigation_action_is_authorized(
    messages: Sequence[ModelMessage],
    action: OpenBusinessRecordsAction,
) -> bool:
    user_message = next(
        (message.content for message in reversed(messages) if message.role == "user"),
        "",
    )
    return bool(
        _NAVIGATION_INTENT.search(user_message)
        and _month_is_visible(user_message, action.start_month)
        and _month_is_visible(user_message, action.end_month)
    )


def _month_is_visible(message: str, month: str) -> bool:
    year, month_number = month.split("-")
    return bool(
        month in message
        or re.search(
            rf"{re.escape(year)}\s*年\s*0?{int(month_number)}\s*月",
            message,
        )
        or (year in message and re.search(rf"(?<!\d)0?{int(month_number)}\s*月", message))
    )


def _navigation_confirmation(action: OpenBusinessRecordsAction) -> str:
    return f"已准备打开 {action.start_month} 至 {action.end_month} 的营业记录筛选视图。"


def _approved_knowledge_answer(
    contextual_results: Sequence[NativeToolResult],
) -> str | None:
    matches = [
        match
        for result in contextual_results
        if isinstance(result.evidence, NativeEvidenceEnvelope)
        and result.evidence.source == ["system_knowledge"]
        for match in result.evidence.facts.get("matches", [])
        if isinstance(match, dict)
        and isinstance(match.get("title"), str)
        and isinstance(match.get("content"), str)
    ]
    if not matches:
        return None
    contents = list(
        dict.fromkeys(match["content"] for match in matches if isinstance(match["content"], str))
    )
    return "\n".join(contents)


def _trusted_period(
    state: ConversationState,
    messages: Sequence[ModelMessage],
) -> MonthlyTotalRevenueArguments | None:
    explicit = _explicit_calendar_month(messages, state)
    if explicit is not None:
        return explicit
    period = state.confirmed_period
    if (
        period is None
        or period.start.day != 1
        or (period.start.year, period.start.month) != (period.end.year, period.end.month)
    ):
        return None
    return MonthlyTotalRevenueArguments(year=period.start.year, month=period.start.month)


def _investigation_context_message(state: ConversationState) -> ModelMessage:
    context = {
        "investigation_goal": state.investigation_goal,
        "confirmed_period": (
            state.confirmed_period.model_dump(mode="json")
            if state.confirmed_period is not None
            else None
        ),
        "confirmed_objects": state.confirmed_objects,
        "analysis_hypotheses": [
            hypothesis.model_dump(mode="json") for hypothesis in state.analysis_hypotheses
        ],
        "pending_directions": state.pending_directions,
        "historical_evidence_references": [
            reference.model_dump(mode="json") for reference in state.evidence_references
        ],
    }
    return ModelMessage(
        role=MessageRole.SYSTEM,
        content=(
            "Current investigation context (trusted server state):\n"
            f"{json.dumps(context, ensure_ascii=False)}\n"
            "Historical evidence references are reference-only and are not current facts. "
            "Any business fact needed for this turn must be reacquired through an available "
            "business tool. Never infer or change user identity or store scope from this context."
        ),
    )
