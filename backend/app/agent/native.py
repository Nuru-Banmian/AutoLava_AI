from __future__ import annotations

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

from app.agent.conversation import AgentRunResult, ConfirmedPeriod, ConversationState
from app.agent.contracts import (
    CurrentStoreScope,
    EvidenceBundle,
    EvidenceCoverage,
    EvidencePeriodResult,
    EvidencePlan,
    ModelMessage,
    MonthlyTotalRevenueResult,
    TurnResult,
)
from app.agent.runtime import RuntimeContext

MONTHLY_TOTAL_REVENUE_TOOL = "monthly_total_revenue"
MAX_NATIVE_TOOL_ROUNDS = 4
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


class NativeEvidenceFailure(ClosedModel):
    status: Literal["none", "failed"]
    category: str | None = Field(default=None, max_length=100)
    message: str | None = Field(default=None, max_length=500)


class NativeEvidenceEnvelope(ClosedModel):
    reference: str = Field(pattern=r"^ev_[0-9a-f]{24}$")
    facts: dict[str, int]
    scope: CurrentStoreScope
    period: EvidencePeriodResult
    unit: Literal["EUR"]
    source: list[Literal["store_daily_records", "settlement_records"]]
    queried_at: datetime
    data_version: str = Field(min_length=1, max_length=100)
    coverage: EvidenceCoverage
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

    @model_validator(mode="after")
    def require_one_item(self) -> NativeTranscriptItem:
        if (self.message is None) == (self.tool_result is None):
            raise ValueError("a transcript item requires exactly one message or tool result")
        return self


class NativeModelTurn(ClosedModel):
    message: ModelMessage
    tool_calls: list[NativeToolCall] = Field(default_factory=list, max_length=4)
    signal: Literal["continue", "end"]

    @model_validator(mode="after")
    def require_signal_shape(self) -> NativeModelTurn:
        if self.message.role != "assistant":
            raise ValueError("native model turns require an assistant message")
        if self.signal == "continue" and not self.tool_calls:
            raise ValueError("continue requires at least one tool call")
        if self.signal == "end" and self.tool_calls:
            raise ValueError("end cannot include tool calls")
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
    """Minimal provider-neutral tool loop for the monthly revenue vertical slice."""

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
        self.tool_registry = (
            NativeToolRegistration(
                definition=NativeToolDefinition(
                    name=MONTHLY_TOTAL_REVENUE_TOOL,
                    description=(
                        "查询当前受信任门店指定自然月的月度总收入，"
                        "包括每日台账营业额与已确认公司结算收入。"
                    ),
                    input_schema=MonthlyTotalRevenueArguments.model_json_schema(),
                ),
                # Historical monthly revenue remains available when optional
                # store data-entry features are disabled.
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
        trusted_period = _explicit_calendar_month(recent_messages)
        if trusted_period is None:
            return AgentRunResult(
                turn=TurnResult(route="clarify", content=EXACT_MONTH_CLARIFICATION),
                state=state.model_copy(
                    update={"pending_clarifications": [EXACT_MONTH_CLARIFICATION]}
                ),
            )
        items = [NativeTranscriptItem(message=message) for message in recent_messages]
        collected: EvidenceBundle | None = None
        for _ in range(MAX_NATIVE_TOOL_ROUNDS):
            turn = await self.model.next_turn(items, tools=tools)
            items.append(NativeTranscriptItem(message=turn.message))
            if turn.signal == "end":
                updated_state = state
                if collected is not None:
                    updated_state = state.model_copy(
                        update={
                            "confirmed_period": ConfirmedPeriod(
                                start=collected.period.start,
                                end=collected.period.end,
                            ),
                            "metrics": ["月度总收入"],
                            "pending_clarifications": [],
                        }
                    )
                return AgentRunResult(
                    turn=TurnResult(route="answer", content=turn.message.content),
                    state=updated_state,
                    evidence=collected,
                )
            if len(turn.tool_calls) != 1:
                raise ValueError("the monthly revenue slice accepts one tool call per round")
            tool_result, new_evidence = await self._execute(
                turn.tool_calls[0],
                catalog_context,
                trusted_period=trusted_period,
            )
            if new_evidence is not None:
                collected = new_evidence
            items.append(NativeTranscriptItem(tool_result=tool_result))
        raise RuntimeError("native tool loop exceeded its round limit")

    async def _execute(
        self,
        call: NativeToolCall,
        context: RuntimeContext,
        *,
        trusted_period: MonthlyTotalRevenueArguments,
    ) -> tuple[NativeToolResult, EvidenceBundle | None]:
        if call.name not in {tool.name for tool in _available_tools(context, self.tool_registry)}:
            raise NativeToolAccessDenied("native tool call is not authorized")
        try:
            arguments = MonthlyTotalRevenueArguments.model_validate(call.arguments)
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
        if arguments != trusted_period:
            return (
                _failed_tool_result(
                    call,
                    fresh_context,
                    trusted_period,
                    self.now(),
                    category="period_scope_mismatch",
                    message="工具期间与用户确认的自然月不一致",
                ),
                None,
            )
        try:
            evidence = await self.evidence_collector.collect(
                EvidencePlan.model_validate(
                    {
                        "requests": [
                            {
                                "kind": "business_metrics",
                                "metric": MONTHLY_TOTAL_REVENUE_TOOL,
                                "period": {
                                    "kind": "calendar_month",
                                    "year": arguments.year,
                                    "month": arguments.month,
                                },
                            }
                        ]
                    }
                ),
                fresh_context,
            )
        except NativeToolAccessDenied:
            raise
        except Exception:
            return _failed_tool_result(call, fresh_context, arguments, self.now()), None
        if not isinstance(evidence, EvidenceBundle) or not isinstance(
            evidence.result, MonthlyTotalRevenueResult
        ):
            return _failed_tool_result(call, fresh_context, arguments, self.now()), None
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
    version_payload = {
        "scope": evidence.current_store.model_dump(mode="json"),
        "period": evidence.period.model_dump(mode="json"),
        "calculation_version": evidence.calculation_version,
        "facts": facts,
        "coverage": evidence.coverage.model_dump(mode="json"),
    }
    digest = hashlib.sha256(
        json.dumps(version_payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    limitations = list(evidence.warnings)
    if evidence.completeness is not None and evidence.completeness.unrecorded_dates:
        limitations.append(f"{len(evidence.completeness.unrecorded_dates)} 个日期没有每日台账记录")
    return NativeEvidenceEnvelope(
        reference=f"ev_{digest[:24]}",
        facts=facts,
        scope=evidence.current_store,
        period=evidence.period,
        unit="EUR",
        source=["store_daily_records", "settlement_records"],
        queried_at=queried_at,
        data_version=f"sha256:{digest}",
        coverage=evidence.coverage,
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
            unit="EUR",
            source=["store_daily_records", "settlement_records"],
            queried_at=queried_at,
            data_version=f"unavailable:{digest}",
            coverage=EvidenceCoverage(
                calendar_dates=(end - start).days + 1,
                recorded_dates=0,
            ),
            limitations=["经营查询暂时失败；未返回任何经营事实"],
            truncated=False,
            failure=NativeEvidenceFailure(
                status="failed",
                category=category,
                message=message,
            ),
        ),
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
