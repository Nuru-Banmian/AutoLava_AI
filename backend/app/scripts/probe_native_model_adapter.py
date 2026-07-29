import argparse
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
from app.agent.model import ModelAdapterError, ModelAttempt, ModelErrorCategory
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
PROBE_PROMPT = (
    "This is a synthetic capability probe. Call probe_alpha and probe_beta "
    "in one parallel tool-call turn, then use both results to finish naturally."
)
ERROR_RELEASE_CASES = {
    ModelErrorCategory.TIMEOUT: "timeout",
    ModelErrorCategory.RATE_LIMIT: "rate_limit",
    ModelErrorCategory.PROVIDER_5XX: "server_error",
    ModelErrorCategory.INVALID_API_KEY: "authentication",
    ModelErrorCategory.INSUFFICIENT_BALANCE: "balance",
    ModelErrorCategory.INVALID_OUTPUT: "invalid_output",
}


def _configured_adapter():
    settings = get_settings()
    primary_profile, _ = configured_openai_profiles(settings)
    return primary_profile, OpenAICompatibleNativeToolModel(primary_profile)


async def probe() -> dict[str, object]:
    primary_profile, adapter = _configured_adapter()
    if (
        primary_profile.input_cost_per_million is None
        or primary_profile.output_cost_per_million is None
    ):
        raise ModelAdapterError(
            "native model probe requires configured input and output cost rates",
            category=ModelErrorCategory.INVALID_REQUEST,
        )
    attempts: list[ModelAttempt] = []
    first = await adapter.next_turn(
        [
            NativeTranscriptItem(
                message=ModelMessage(
                    role="user",
                    content=PROBE_PROMPT,
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
                content=PROBE_PROMPT,
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
    if not attempts or any(
        attempt.input_tokens is None
        or attempt.output_tokens is None
        or attempt.estimated_cost is None
        for attempt in attempts
    ):
        raise ModelAdapterError(
            "native model probe did not receive complete usage metrics",
            category=ModelErrorCategory.INVALID_OUTPUT,
        )
    release_cases = [
        {"case": case, "passed": True}
        for case in (
            "native_tool_calling",
            "parallel_tool_calls",
            "tool_result_continuation",
            "natural_answer",
            "usage_metrics",
        )
    ]
    return {
        "status": "passed",
        "provider": primary_profile.provider,
        "model": primary_profile.model_id,
        "parallel_tool_calls": len(first.tool_calls),
        "tool_result_continuation": True,
        "natural_end": True,
        "attempts": len(attempts),
        "input_tokens": sum(attempt.input_tokens for attempt in attempts),
        "output_tokens": sum(attempt.output_tokens for attempt in attempts),
        "latency_ms": sum(attempt.latency_ms for attempt in attempts),
        "estimated_cost_eur": sum(attempt.estimated_cost for attempt in attempts),
        "release_cases": release_cases,
    }


async def probe_expected_error(
    expected_category: ModelErrorCategory,
) -> dict[str, object]:
    if expected_category not in ERROR_RELEASE_CASES:
        raise ModelAdapterError(
            "unsupported native model error probe category",
            category=ModelErrorCategory.INVALID_REQUEST,
        )
    primary_profile, adapter = _configured_adapter()
    observed_category = None
    try:
        await adapter.next_turn(
            [
                NativeTranscriptItem(
                    message=ModelMessage(
                        role="user",
                        content=(
                            "This is a synthetic error-mapping probe. "
                            "Return a short natural answer."
                        ),
                    )
                )
            ],
            tools=(),
        )
    except ModelAdapterError as error:
        observed_category = error.category
    if observed_category != expected_category:
        raise ModelAdapterError(
            "native model error probe did not observe the expected category",
            category=ModelErrorCategory.INVALID_OUTPUT,
        )
    return {
        "status": "passed",
        "provider": primary_profile.provider,
        "model": primary_profile.model_id,
        "expected_error_category": expected_category.value,
        "observed_error_category": observed_category.value,
        "release_cases": [
            {
                "case": ERROR_RELEASE_CASES[expected_category],
                "passed": True,
            }
        ],
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
    parser = argparse.ArgumentParser(
        description="Probe a real native model Adapter with synthetic, non-business data."
    )
    parser.add_argument(
        "--expect-error",
        choices=[category.value for category in ERROR_RELEASE_CASES],
        help="Require one real provider failure to map to this provider-neutral category.",
    )
    arguments = parser.parse_args()
    try:
        report = asyncio.run(
            probe_expected_error(ModelErrorCategory(arguments.expect_error))
            if arguments.expect_error
            else probe()
        )
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
