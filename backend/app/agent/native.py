from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Sequence
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.business_evidence import BusinessEvidenceCollector
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


class FakeNativeToolModel:
    """Scriptable native-tool model used by high-level acceptance tests."""

    def __init__(self, *, turns: Iterable[NativeModelTurn | dict[str, Any]]) -> None:
        self._turns = list(turns)
        self.calls: list[NativeModelCall] = []

    async def next_turn(
        self,
        items: Sequence[NativeTranscriptItem],
        *,
        tools: Sequence[NativeToolDefinition],
    ) -> NativeModelTurn:
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
        evidence_collector: BusinessEvidenceCollector,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self.model = model
        self.evidence_collector = evidence_collector
        self.now = now
        self.tools = [
            NativeToolDefinition(
                name=MONTHLY_TOTAL_REVENUE_TOOL,
                description=(
                    "查询当前受信任门店指定自然月的月度总收入，"
                    "包括每日台账营业额与已确认公司结算收入。"
                ),
                input_schema={
                    "type": "object",
                    "properties": {
                        "year": {"type": "integer", "minimum": 2000, "maximum": 2200},
                        "month": {"type": "integer", "minimum": 1, "maximum": 12},
                    },
                    "required": ["year", "month"],
                    "additionalProperties": False,
                },
            )
        ]

    async def run(
        self,
        context: RuntimeContext,
        state: ConversationState,
        recent_messages: list[ModelMessage],
    ) -> AgentRunResult:
        items = [NativeTranscriptItem(message=message) for message in recent_messages]
        collected: EvidenceBundle | None = None
        for _ in range(MAX_NATIVE_TOOL_ROUNDS):
            turn = await self.model.next_turn(items, tools=self.tools)
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
            tool_result, collected = await self._execute(turn.tool_calls[0], context)
            items.append(NativeTranscriptItem(tool_result=tool_result))
        raise RuntimeError("native tool loop exceeded its round limit")

    async def _execute(
        self,
        call: NativeToolCall,
        context: RuntimeContext,
    ) -> tuple[NativeToolResult, EvidenceBundle]:
        if call.name != MONTHLY_TOTAL_REVENUE_TOOL:
            raise ValueError("unavailable native tool")
        if set(call.arguments) != {"year", "month"}:
            raise ValueError("monthly revenue accepts only year and month")
        year = call.arguments["year"]
        month = call.arguments["month"]
        if (
            isinstance(year, bool)
            or not isinstance(year, int)
            or not 2000 <= year <= 2200
            or isinstance(month, bool)
            or not isinstance(month, int)
            or not 1 <= month <= 12
        ):
            raise ValueError("invalid monthly revenue period")
        evidence = await self.evidence_collector.collect(
            EvidencePlan.model_validate(
                {
                    "requests": [
                        {
                            "kind": "business_metrics",
                            "metric": MONTHLY_TOTAL_REVENUE_TOOL,
                            "period": {
                                "kind": "calendar_month",
                                "year": year,
                                "month": month,
                            },
                        }
                    ]
                }
            ),
            context,
        )
        if not isinstance(evidence, EvidenceBundle) or not isinstance(
            evidence.result, MonthlyTotalRevenueResult
        ):
            raise RuntimeError("monthly revenue tool returned incompatible evidence")
        envelope = _native_envelope(evidence, queried_at=self.now())
        return (
            NativeToolResult(
                call_id=call.id,
                name=call.name,
                evidence=envelope,
            ),
            evidence,
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
        limitations=limitations,
        truncated=evidence.truncated,
        failure=NativeEvidenceFailure(status="none"),
    )
