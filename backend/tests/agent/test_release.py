import json

from app.agent.release import (
    ReleaseSample,
    agent_adapter_config_sha256,
    agent_release_status,
    summarize_release_samples,
)
from app.core.config import Settings


def approved_report(settings: Settings) -> dict[str, object]:
    return {
        "schema_version": 1,
        "target": {
            "memory_limit_mb": 2048,
            "single_container": True,
        },
        "profile": {
            "provider": "candidate",
            "model": "candidate-model",
            "fallback_provider": "backup",
            "fallback_model": "backup-model",
            "timeout_seconds": 30,
            "max_output_tokens": 2000,
            "input_cost_per_million": 1,
            "output_cost_per_million": 2,
            "evidence_batch_limit": 1,
            "adapter_config_sha256": agent_adapter_config_sha256(settings),
        },
        "evidence": {
            "collected_at": "2026-07-27T12:00:00Z",
            "collector_version": "agent-release-v1",
            "container_image_digest": f"sha256:{'1' * 64}",
            "measurement_artifact_sha256": "2" * 64,
            "adapter_cases_artifact_sha256": "3" * 64,
            "transaction_trace_artifact_sha256": "4" * 64,
        },
        "measurements": {
            "serial_sample_count": 20,
            "idle_peak_memory_mb": 420,
            "business_peak_memory_mb": 610,
            "agent_peak_memory_mb": 1320,
            "request_p95_ms": 9000,
            "model_stage_count_max": 2,
            "input_tokens_max": 4500,
            "output_tokens_max": 900,
            "estimated_cost_eur_max": 0.02,
            "sqlite_snapshot_p95_ms": 120,
            "short_write_baseline_p95_ms": 35,
            "short_write_with_agent_p95_ms": 70,
            "language_quality_pass_rate": 1,
        },
        "checks": {
            "language_quality": True,
            "structured_output": True,
            "failure_semantics": True,
            "model_calls_outside_sqlite_transactions": True,
            "safety_release_gate": True,
            "secrets_redacted": True,
            "business_content_redacted": True,
        },
        "thresholds": {
            "minimum_serial_samples": 20,
            "minimum_free_memory_mb": 256,
            "language_quality_pass_rate": 1,
            "request_p95_ms": 15000,
            "estimated_cost_eur_max": 0.05,
            "sqlite_snapshot_p95_ms": 500,
            "short_write_with_agent_p95_ms": 200,
            "short_write_slowdown_max": 3,
        },
    }


def production_settings(report_path) -> Settings:
    return Settings(
        _env_file=None,
        environment="production",
        database_path=report_path.parent / "production.sqlite3",
        jwt_secret="a" * 32,
        model_adapter="openai_compatible",
        model_provider="candidate",
        model_base_url="https://provider.invalid/v1",
        model_id="candidate-model",
        model_api_key="test-only-key",
        model_input_cost_per_million=1,
        model_output_cost_per_million=2,
        fallback_model_provider="backup",
        fallback_model_base_url="https://backup.invalid/v1",
        fallback_model_id="backup-model",
        fallback_model_api_key="test-only-backup-key",
        fallback_model_input_cost_per_million=3,
        fallback_model_output_cost_per_million=4,
        agent_release_report_path=str(report_path),
    )


def test_production_agent_release_requires_a_complete_matching_pass_report(tmp_path) -> None:
    report_path = tmp_path / "agent-release.json"
    settings = production_settings(report_path)

    missing = agent_release_status(settings)
    assert missing.approved is False
    assert missing.blockers == ["release report is missing"]

    report = approved_report(settings)
    report["checks"]["structured_output"] = False
    report_path.write_text(json.dumps(report), encoding="utf-8")
    failed = agent_release_status(settings)
    assert failed.approved is False
    assert "structured output validation failed" in failed.blockers

    report["checks"]["structured_output"] = True
    report_path.write_text(json.dumps(report), encoding="utf-8")
    passed = agent_release_status(settings)
    assert passed.approved is True
    assert passed.blockers == []


def test_release_report_cannot_approve_a_different_runtime_profile(tmp_path) -> None:
    report_path = tmp_path / "agent-release.json"
    measured_settings = production_settings(report_path)
    report_path.write_text(
        json.dumps(approved_report(measured_settings)), encoding="utf-8"
    )
    settings = measured_settings.model_copy(
        update={"model_id": "unmeasured-model"}
    )

    status = agent_release_status(settings)

    assert status.approved is False
    assert status.blockers == ["runtime model profile does not match the evaluated profile"]


def test_release_report_cannot_weaken_the_repository_thresholds(tmp_path) -> None:
    report_path = tmp_path / "agent-release.json"
    settings = production_settings(report_path)
    report = approved_report(settings)
    report["thresholds"]["minimum_free_memory_mb"] = 1
    report_path.write_text(json.dumps(report), encoding="utf-8")

    status = agent_release_status(settings)

    assert status.approved is False
    assert status.blockers == ["release thresholds do not match the approved policy"]


def test_release_report_rejects_zero_measurements_instead_of_treating_them_as_passes(
    tmp_path,
) -> None:
    report_path = tmp_path / "agent-release.json"
    settings = production_settings(report_path)
    report = approved_report(settings)
    report["measurements"]["agent_peak_memory_mb"] = 0
    report_path.write_text(json.dumps(report), encoding="utf-8")

    status = agent_release_status(settings)

    assert status.approved is False
    assert status.blockers == ["release report is invalid"]


def test_release_report_requires_auditable_evidence_artifacts(tmp_path) -> None:
    report_path = tmp_path / "agent-release.json"
    settings = production_settings(report_path)
    report = approved_report(settings)
    del report["evidence"]
    report_path.write_text(json.dumps(report), encoding="utf-8")

    status = agent_release_status(settings)

    assert status.approved is False
    assert status.blockers == ["release report is invalid"]


def test_release_sample_summary_uses_nearest_rank_p95_and_preserves_maxima() -> None:
    samples = [
        ReleaseSample(
            sample_index=index,
            idle_peak_memory_mb=400 + index,
            business_peak_memory_mb=500 + index,
            agent_peak_memory_mb=1000 + index,
            request_ms=1000 + index,
            model_stage_count=index % 2 + 1,
            input_tokens=200 + index,
            output_tokens=100 + index,
            estimated_cost_eur=index / 1000,
            sqlite_snapshot_ms=20 + index,
            short_write_baseline_ms=10 + index,
            short_write_with_agent_ms=30 + index,
            language_quality_passed=index != 20,
        )
        for index in range(1, 21)
    ]

    measurements = summarize_release_samples(samples)

    assert measurements.serial_sample_count == 20
    assert measurements.request_p95_ms == 1019
    assert measurements.model_stage_count_max == 2
    assert measurements.input_tokens_max == 220
    assert measurements.language_quality_pass_rate == 0.95

def test_release_report_requires_serial_samples_and_language_quality(tmp_path) -> None:
    report_path = tmp_path / "agent-release.json"
    settings = production_settings(report_path)
    report = approved_report(settings)
    report["measurements"]["serial_sample_count"] = 19
    report["measurements"]["language_quality_pass_rate"] = 0.95
    report["checks"]["language_quality"] = False
    report_path.write_text(json.dumps(report), encoding="utf-8")

    status = agent_release_status(settings)

    assert status.approved is False
    assert "release measurements need at least 20 serial samples" in status.blockers
    assert "language quality does not meet the release threshold" in status.blockers
    assert "language quality validation failed" in status.blockers


def test_release_report_binds_structured_output_thinking_and_fallback_costs(
    tmp_path,
) -> None:
    report_path = tmp_path / "agent-release.json"
    measured = production_settings(report_path)
    report_path.write_text(json.dumps(approved_report(measured)), encoding="utf-8")
    changed = measured.model_copy(
        update={
            "model_thinking_parameters": {"reasoning_effort": "high"},
            "fallback_model_output_cost_per_million": 99,
        }
    )

    status = agent_release_status(changed)

    assert status.approved is False
    assert status.blockers == ["runtime model profile does not match the evaluated profile"]


def test_release_report_cannot_approve_the_fake_adapter(tmp_path) -> None:
    report_path = tmp_path / "agent-release.json"
    measured = production_settings(report_path)
    report_path.write_text(json.dumps(approved_report(measured)), encoding="utf-8")

    status = agent_release_status(
        measured.model_copy(update={"model_adapter": "fake"})
    )

    assert status.approved is False
    assert status.blockers == [
        "production release requires openai_compatible adapter",
        "runtime model profile does not match the evaluated profile",
    ]


def test_non_production_keeps_the_fake_adapter_development_seam_open() -> None:
    status = agent_release_status(Settings(_env_file=None))

    assert status.approved is True
    assert status.blockers == []
