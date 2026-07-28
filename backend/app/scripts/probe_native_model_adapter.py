import asyncio
from datetime import date, datetime, timezone
from hashlib import sha256
import json

from app.agent.contracts import (
    CurrentStoreScope,
    EvidenceCoverage,
    EvidencePeriodResult,
    ModelMessage,
)
from app.agent.factory import configured_openai_profiles
from app.agent.model import ModelAdapterError, ModelAttempt
from app.agent.native import (
    NativeEvidenceEnvelope,
    NativeEvidenceFailure,
    NativeToolDefinition,
    NativeToolResult,
    NativeTranscriptItem,
)
from app.agent.native_model import OpenAICompatibleNativeToolModel
from app.core.config import get_settings


PROBE_TOOLS = (
    NativeToolDefinition(
        name="probe_alpha",
        description="Return the supplied synthetic probe label.",
        input_schema={
            "type": "object",
            "properties": {"label": {"type": "string", "const": "alpha"}},
            "required": ["label"],
            "additionalProperties": False,
        },
    ),
    NativeToolDefinition(
        name="probe_beta",
        description="Return the supplied synthetic probe label.",
        input_schema={
            "type": "object",
            "properties": {"label": {"type": "string", "const": "beta"}},
            "required": ["label"],
            "additionalProperties": False,
        },
    ),
)


async def probe() -> dict[str, object]:
    settings = get_settings()
    primary_profile, _ = configured_openai_profiles(settings)
    adapter = OpenAICompatibleNativeToolModel(primary_profile)
    attempts: list[ModelAttempt] = []
    first = await adapter.next_turn(
        [
            NativeTranscriptItem(
                message=ModelMessage(
                    role="user",
                    content=(
                        "This is a synthetic capability probe. Call probe_alpha and probe_beta "
                        "in one parallel tool-call turn, then use both results to finish naturally."
                    ),
                )
            )
        ],
        tools=PROBE_TOOLS,
        observer=attempts.append,
    )
    if first.signal != "continue" or {call.name for call in first.tool_calls} != {
        "probe_alpha",
        "probe_beta",
    }:
        raise ModelAdapterError("native parallel tool calling was not observed")
    continued_items = [
        NativeTranscriptItem(
            message=ModelMessage(
                role="user",
                content=(
                    "This is a synthetic capability probe. Call probe_alpha and probe_beta "
                    "in one parallel tool-call turn, then use both results to finish naturally."
                ),
            )
        ),
        NativeTranscriptItem(message=first.message, tool_calls=first.tool_calls),
        *[
            NativeTranscriptItem(tool_result=_synthetic_result(call.id, call.name))
            for call in first.tool_calls
        ],
    ]
    final = await adapter.next_turn(
        continued_items,
        tools=PROBE_TOOLS,
        observer=attempts.append,
    )
    if final.signal != "end":
        raise ModelAdapterError("native tool result continuation did not end naturally")
    return {
        "status": "passed",
        "provider": primary_profile.provider,
        "model": primary_profile.model_id,
        "parallel_tool_calls": len(first.tool_calls),
        "tool_result_continuation": True,
        "natural_end": True,
        "attempts": len(attempts),
        "input_tokens": sum(attempt.input_tokens or 0 for attempt in attempts),
        "output_tokens": sum(attempt.output_tokens or 0 for attempt in attempts),
        "latency_ms": sum(attempt.latency_ms for attempt in attempts),
        "estimated_cost_eur": sum(attempt.estimated_cost or 0 for attempt in attempts),
    }


def _synthetic_result(call_id: str, name: str) -> NativeToolResult:
    reference = f"ev_{sha256(call_id.encode()).hexdigest()[:24]}"
    return NativeToolResult(
        call_id=call_id,
        name=name,
        evidence=NativeEvidenceEnvelope(
            reference=reference,
            facts={"probe": name, "result": "ok"},
            scope=CurrentStoreScope(id=1),
            period=EvidencePeriodResult(start=date(2026, 1, 1), end=date(2026, 1, 1)),
            unit="unknown",
            source=["system_knowledge"],
            queried_at=datetime.now(timezone.utc),
            data_version="synthetic-probe-v1",
            coverage=EvidenceCoverage(calendar_dates=1, recorded_dates=1),
            limitations=["Synthetic probe data only; not business evidence."],
            truncated=False,
            failure=NativeEvidenceFailure(status="none"),
        ),
    )


def main() -> int:
    try:
        report = asyncio.run(probe())
    except ModelAdapterError as error:
        report = {
            "status": "failed",
            "error_category": error.category.value,
        }
        print(json.dumps(report, ensure_ascii=False))
        return 1
    print(json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
