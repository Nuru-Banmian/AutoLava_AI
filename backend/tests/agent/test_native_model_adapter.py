import json

import pytest
from langchain_core.messages import AIMessage, ToolMessage
from pydantic import SecretStr

from app.agent.contracts import ModelMessage
from app.agent.conversation import ConversationState
from app.agent.model import (
    ModelAdapterError,
    ModelAttempt,
    ModelErrorCategory,
    OpenAICompatibleProfile,
)
from app.agent.native import (
    NativeModelUsage,
    NativeModelTurn,
    NativeToolAgentService,
    NativeToolCall,
    NativeToolDefinition,
    NativeToolResult,
    NativeTranscriptItem,
)
from app.agent.native_model import (
    OpenAICompatibleNativeToolModel,
    ResilientNativeToolModel,
)
from app.agent.runtime import RuntimeContext, RuntimeFeatureFlags


TOOLS = [
    NativeToolDefinition(
        name="monthly_total_revenue",
        description="查询月度总收入。",
        input_schema={
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
            "additionalProperties": False,
        },
    ),
    NativeToolDefinition(
        name="operating_days",
        description="查询经营日。",
        input_schema={
            "type": "object",
            "properties": {
                "year": {"type": "integer"},
                "month": {"type": "integer"},
            },
            "required": ["year", "month"],
            "additionalProperties": False,
        },
    ),
]


def _profile(
    *,
    provider: str = "candidate",
    model_id: str = "candidate-model",
) -> OpenAICompatibleProfile:
    return OpenAICompatibleProfile(
        provider=provider,
        base_url="https://provider.invalid/v1",
        model_id=model_id,
        api_key=SecretStr("provider-secret"),
        input_cost_per_million=1,
        output_cost_per_million=2,
    )


class ScriptedNativeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.bound_tools = []
        self.calls = []

    def bind_tools(self, tools):
        self.bound_tools.append(tools)
        return self

    async def ainvoke(self, messages):
        self.calls.append(messages)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


async def test_production_native_adapter_supports_parallel_tool_calls_and_usage() -> None:
    client = ScriptedNativeClient(
        [
            AIMessage(
                content="我先并行核对收入和经营日。",
                tool_calls=[
                    {
                        "id": "revenue",
                        "name": "monthly_total_revenue",
                        "args": {"year": 2026, "month": 7},
                        "type": "tool_call",
                    },
                    {
                        "id": "days",
                        "name": "operating_days",
                        "args": {"year": 2026, "month": 7},
                        "type": "tool_call",
                    },
                ],
                usage_metadata={
                    "input_tokens": 80,
                    "output_tokens": 20,
                    "total_tokens": 100,
                },
            )
        ]
    )
    attempts = []
    adapter = OpenAICompatibleNativeToolModel(_profile(), client=client)

    turn = await adapter.next_turn(
        [NativeTranscriptItem(message=ModelMessage(role="user", content="调查七月经营情况"))],
        tools=TOOLS,
        observer=attempts.append,
    )

    assert turn.signal == "continue"
    assert turn.tool_calls == [
        NativeToolCall(
            id="revenue",
            name="monthly_total_revenue",
            arguments={"year": 2026, "month": 7},
        ),
        NativeToolCall(
            id="days",
            name="operating_days",
            arguments={"year": 2026, "month": 7},
        ),
    ]
    assert turn.usage == NativeModelUsage(
        input_tokens=80,
        output_tokens=20,
        estimated_cost_eur=0.00012,
    )
    assert [tool["function"]["name"] for tool in client.bound_tools[0]] == [
        "monthly_total_revenue",
        "operating_days",
    ]
    assert attempts[0].provider == "candidate"
    assert attempts[0].model == "candidate-model"
    assert attempts[0].estimated_cost == pytest.approx(0.00012)


async def test_production_native_adapter_continues_tool_results_and_ends_naturally() -> None:
    evidence_reference = "ev_000000000000000000000000"
    final_payload = {
        "answer": "2026 年 7 月月度总收入为 140 欧元。",
        "answer_claims": [
            {
                "statement": "2026 年 7 月月度总收入为 140 欧元",
                "status": "verified_fact",
                "metric": "monthly_total_revenue",
                "period": {"start": "2026-07-01", "end": "2026-07-31"},
                "value": 140,
                "unit": "EUR",
                "evidence_references": [evidence_reference],
            }
        ],
    }
    client = ScriptedNativeClient([AIMessage(content=json.dumps(final_payload))])
    adapter = OpenAICompatibleNativeToolModel(_profile(), client=client)
    call = NativeToolCall(
        id="revenue",
        name="monthly_total_revenue",
        arguments={"year": 2026, "month": 7},
    )
    result = NativeToolResult.model_validate(
        {
            "call_id": "revenue",
            "name": "monthly_total_revenue",
            "evidence": {
                "reference": evidence_reference,
                "scope": {"id": 7},
                "period": {"start": "2026-07-01", "end": "2026-07-31"},
                "facts": {
                    "metric": "monthly_total_revenue",
                    "value": 140,
                    "unit": "EUR",
                },
                "unit": "EUR",
                "source": ["store_daily_records", "settlement_records"],
                "queried_at": "2026-07-28T10:00:00Z",
                "data_version": "v1",
                "coverage": {
                    "calendar_dates": 31,
                    "recorded_dates": 31,
                },
                "limitations": [],
                "truncated": False,
                "failure": {"status": "none"},
            },
        }
    )

    turn = await adapter.next_turn(
        [
            NativeTranscriptItem(message=ModelMessage(role="user", content="七月收入？")),
            NativeTranscriptItem(
                message=ModelMessage(role="assistant", content="我先查询月度总收入。"),
                tool_calls=[call],
            ),
            NativeTranscriptItem(tool_result=result),
        ],
        tools=TOOLS,
    )

    assert turn.signal == "end"
    assert turn.message.content == "2026 年 7 月月度总收入为 140 欧元。"
    assert turn.answer_claims[0].evidence_references == [evidence_reference]
    provider_messages = client.calls[0]
    assert provider_messages[-2].tool_calls[0]["id"] == "revenue"
    assert isinstance(provider_messages[-1], ToolMessage)
    assert provider_messages[-1].tool_call_id == "revenue"
    assert evidence_reference in provider_messages[-1].content
    assert "provider-secret" not in repr(provider_messages)


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        (TimeoutError("secret timeout detail"), ModelErrorCategory.TIMEOUT),
        (type("RateLimitError", (RuntimeError,), {"status_code": 429})("secret"), ModelErrorCategory.RATE_LIMIT),
        (type("ProviderError", (RuntimeError,), {"status_code": 503})("secret"), ModelErrorCategory.PROVIDER_5XX),
        (type("AuthError", (RuntimeError,), {"status_code": 401})("secret"), ModelErrorCategory.INVALID_API_KEY),
        (ValueError("malformed provider payload"), ModelErrorCategory.INVALID_OUTPUT),
    ],
)
async def test_production_native_adapter_maps_failures_without_leaking_payload(
    failure: Exception,
    category: ModelErrorCategory,
) -> None:
    adapter = OpenAICompatibleNativeToolModel(
        _profile(),
        client=ScriptedNativeClient([failure]),
    )
    attempts = []

    with pytest.raises(ModelAdapterError) as raised:
        await adapter.next_turn([], tools=TOOLS, observer=attempts.append)

    assert raised.value.category == category
    assert str(raised.value) == "provider request failed"
    assert attempts[0].error_category == category


async def test_resilient_native_adapter_retries_primary_then_uses_fallback() -> None:
    transient = type("ProviderError", (RuntimeError,), {"status_code": 503})
    primary = OpenAICompatibleNativeToolModel(
        _profile(),
        client=ScriptedNativeClient(
            [transient("first private payload"), transient("second private payload")]
        ),
    )
    fallback = OpenAICompatibleNativeToolModel(
        _profile(provider="backup", model_id="backup-model"),
        client=ScriptedNativeClient([AIMessage(content="这是自然结束回答。")]),
    )
    attempts = []
    adapter = ResilientNativeToolModel(
        primary,
        fallback=fallback,
        retry_attempts=1,
    )

    turn = await adapter.next_turn([], tools=TOOLS, observer=attempts.append)

    assert turn.signal == "end"
    assert turn.message.content == "这是自然结束回答。"
    assert [attempt.result for attempt in attempts] == ["failure", "failure", "success"]
    assert [attempt.is_fallback for attempt in attempts] == [False, False, True]


async def test_resilient_native_adapter_reports_all_providers_unavailable() -> None:
    transient = type("ProviderError", (RuntimeError,), {"status_code": 503})
    primary = OpenAICompatibleNativeToolModel(
        _profile(),
        client=ScriptedNativeClient([transient("primary private payload")]),
    )
    fallback = OpenAICompatibleNativeToolModel(
        _profile(provider="backup", model_id="backup-model"),
        client=ScriptedNativeClient([transient("backup private payload")]),
    )
    adapter = ResilientNativeToolModel(primary, fallback=fallback, retry_attempts=0)

    with pytest.raises(ModelAdapterError) as raised:
        await adapter.next_turn([], tools=TOOLS)

    assert raised.value.category == ModelErrorCategory.PROVIDER_5XX
    assert str(raised.value) == "all model providers unavailable"


async def test_native_service_returns_attempts_for_existing_observability_persistence() -> None:
    class ObservedEndingModel:
        async def next_turn(self, items, *, tools, observer=None):
            del items, tools
            if observer is not None:
                observer(
                    ModelAttempt(
                        stage="plan",
                        provider="candidate",
                        model="candidate-model",
                        result="success",
                        error_category=None,
                        latency_ms=12,
                        input_tokens=7,
                        output_tokens=3,
                        estimated_cost=0.000013,
                    )
                )
            return NativeModelTurn(
                message=ModelMessage(role="assistant", content="你好。"),
                usage=NativeModelUsage(input_tokens=7, output_tokens=3),
                signal="end",
            )

    class PassthroughScopeResolver:
        async def refresh(self, context):
            return context

    class UnusedEvidenceCollector:
        async def collect(self, plan, context):
            raise AssertionError(f"unexpected evidence call: {plan!r}, {context!r}")

    service = NativeToolAgentService(
        model=ObservedEndingModel(),
        evidence_collector=UnusedEvidenceCollector(),
        scope_resolver=PassthroughScopeResolver(),
    )
    context = RuntimeContext(
        user_id=1,
        store_id=2,
        role="admin",
        store_timezone="Europe/Rome",
        features=RuntimeFeatureFlags(
            agent_enabled=True,
            company_settlement_enabled=True,
            income_items_enabled=True,
            wash_count_enabled=True,
        ),
    )

    result = await service.run(
        context,
        ConversationState(),
        [ModelMessage(role="user", content="你好")],
    )

    assert len(result.attempts) == 1
    assert result.attempts[0].provider == "candidate"
    assert result.attempts[0].input_tokens == 7
