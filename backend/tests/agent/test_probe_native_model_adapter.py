import pytest

from app.agent.contracts import ModelMessage
from app.agent.model import (
    ModelAdapterError,
    ModelAttempt,
    ModelErrorCategory,
    OpenAICompatibleProfile,
)
from app.agent.native import NativeModelTurn, NativeModelUsage, NativeToolCall
from app.scripts import probe_native_model_adapter


def _profile() -> OpenAICompatibleProfile:
    return OpenAICompatibleProfile(
        provider="candidate",
        base_url="https://models.example.test/v1",
        model_id="candidate-model",
        api_key="secret",
        input_cost_per_million=1,
        output_cost_per_million=2,
    )


class ScriptedProbeAdapter:
    include_usage = True

    def __init__(self, profile: OpenAICompatibleProfile) -> None:
        self.profile = profile
        self.calls = 0

    async def next_turn(self, items, *, tools, observer):
        assert self.profile == _profile()
        assert {tool.name for tool in tools} == {"probe_alpha", "probe_beta"}
        self.calls += 1
        observer(
            ModelAttempt(
                stage="plan" if self.calls == 1 else "answer",
                provider="candidate",
                model="candidate-model",
                result="success",
                error_category=None,
                latency_ms=12,
                input_tokens=7 if self.include_usage else None,
                output_tokens=3 if self.include_usage else None,
                estimated_cost=0.000013 if self.include_usage else None,
            )
        )
        if self.calls == 1:
            return NativeModelTurn(
                message=ModelMessage(role="assistant", content="正在调用合成探针工具。"),
                tool_calls=[
                    NativeToolCall(
                        id="alpha-call", name="probe_alpha", arguments={"label": "alpha"}
                    ),
                    NativeToolCall(id="beta-call", name="probe_beta", arguments={"label": "beta"}),
                ],
                usage=NativeModelUsage(),
                signal="continue",
            )
        assert {item.tool_result.call_id for item in items if item.tool_result is not None} == {
            "alpha-call",
            "beta-call",
        }
        return NativeModelTurn(
            message=ModelMessage(role="assistant", content="探针已自然完成。"),
            usage=NativeModelUsage(input_tokens=7, output_tokens=3),
            signal="end",
        )


async def test_probe_emits_release_cases_for_a_real_native_tool_round_trip(monkeypatch) -> None:
    monkeypatch.setattr(
        probe_native_model_adapter,
        "configured_openai_profiles",
        lambda settings: (_profile(), None),
    )
    monkeypatch.setattr(
        probe_native_model_adapter,
        "OpenAICompatibleNativeToolModel",
        ScriptedProbeAdapter,
    )

    report = await probe_native_model_adapter.probe()

    assert report == {
        "status": "passed",
        "provider": "candidate",
        "model": "candidate-model",
        "parallel_tool_calls": 2,
        "tool_result_continuation": True,
        "natural_end": True,
        "attempts": 2,
        "input_tokens": 14,
        "output_tokens": 6,
        "latency_ms": 24,
        "estimated_cost_eur": 0.000026,
        "release_cases": [
            {"case": "native_tool_calling", "passed": True},
            {"case": "parallel_tool_calls", "passed": True},
            {"case": "tool_result_continuation", "passed": True},
            {"case": "natural_answer", "passed": True},
            {"case": "usage_metrics", "passed": True},
        ],
    }


async def test_probe_rejects_a_provider_that_omits_usage_metrics(monkeypatch) -> None:
    class MissingUsageProbeAdapter(ScriptedProbeAdapter):
        include_usage = False

    monkeypatch.setattr(
        probe_native_model_adapter,
        "configured_openai_profiles",
        lambda settings: (_profile(), None),
    )
    monkeypatch.setattr(
        probe_native_model_adapter,
        "OpenAICompatibleNativeToolModel",
        MissingUsageProbeAdapter,
    )

    with pytest.raises(ModelAdapterError) as raised:
        await probe_native_model_adapter.probe()

    assert raised.value.category == ModelErrorCategory.INVALID_OUTPUT


async def test_error_probe_requires_the_real_adapter_to_map_the_expected_failure(
    monkeypatch,
) -> None:
    class RateLimitedProbeAdapter:
        def __init__(self, profile: OpenAICompatibleProfile) -> None:
            assert profile == _profile()

        async def next_turn(self, items, *, tools):
            assert items
            assert tools == ()
            raise ModelAdapterError(
                "provider-private rate limit payload",
                category=ModelErrorCategory.RATE_LIMIT,
            )

    monkeypatch.setattr(
        probe_native_model_adapter,
        "configured_openai_profiles",
        lambda settings: (_profile(), None),
    )
    monkeypatch.setattr(
        probe_native_model_adapter,
        "OpenAICompatibleNativeToolModel",
        RateLimitedProbeAdapter,
    )

    report = await probe_native_model_adapter.probe_expected_error(ModelErrorCategory.RATE_LIMIT)

    assert report == {
        "status": "passed",
        "provider": "candidate",
        "model": "candidate-model",
        "expected_error_category": "rate_limit",
        "observed_error_category": "rate_limit",
        "release_cases": [{"case": "rate_limit", "passed": True}],
    }
