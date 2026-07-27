from datetime import datetime
from hashlib import sha256
import json
from math import ceil
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.agent.factory import configured_openai_profiles
from app.core.config import Settings


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseTarget(ClosedModel):
    memory_limit_mb: int = Field(gt=0)
    single_container: bool


class ReleaseProfile(ClosedModel):
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    timeout_seconds: float = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    input_cost_per_million: float = Field(gt=0)
    output_cost_per_million: float = Field(gt=0)
    evidence_batch_limit: int = Field(gt=0)
    adapter_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_settings(cls, settings: Settings) -> "ReleaseProfile":
        fallback_provider = (
            settings.fallback_model_provider if settings.fallback_model_id else None
        )
        return cls(
            provider=settings.model_provider,
            model=settings.model_id,
            fallback_provider=fallback_provider,
            fallback_model=settings.fallback_model_id or None,
            timeout_seconds=settings.model_timeout_seconds,
            max_output_tokens=settings.model_max_output_tokens,
            input_cost_per_million=settings.model_input_cost_per_million,
            output_cost_per_million=settings.model_output_cost_per_million,
            evidence_batch_limit=settings.agent_evidence_batch_limit,
            adapter_config_sha256=agent_adapter_config_sha256(settings),
        )


class ReleaseEvidence(ClosedModel):
    collected_at: datetime
    collector_version: Literal["agent-release-v1"]
    container_image_digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    measurement_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    adapter_cases_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    transaction_trace_artifact_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ReleaseMeasurements(ClosedModel):
    serial_sample_count: int = Field(ge=1)
    idle_peak_memory_mb: float = Field(gt=0)
    business_peak_memory_mb: float = Field(gt=0)
    agent_peak_memory_mb: float = Field(gt=0)
    request_p95_ms: float = Field(gt=0)
    model_stage_count_max: int = Field(ge=1)
    input_tokens_max: int = Field(gt=0)
    output_tokens_max: int = Field(gt=0)
    estimated_cost_eur_max: float = Field(gt=0)
    sqlite_snapshot_p95_ms: float = Field(gt=0)
    short_write_baseline_p95_ms: float = Field(gt=0)
    short_write_with_agent_p95_ms: float = Field(gt=0)
    language_quality_pass_rate: float = Field(ge=0, le=1)


class ReleaseSample(ClosedModel):
    sample_index: int = Field(ge=1)
    idle_peak_memory_mb: float = Field(gt=0)
    business_peak_memory_mb: float = Field(gt=0)
    agent_peak_memory_mb: float = Field(gt=0)
    request_ms: float = Field(gt=0)
    model_stage_count: int = Field(ge=1)
    input_tokens: int = Field(gt=0)
    output_tokens: int = Field(gt=0)
    estimated_cost_eur: float = Field(gt=0)
    sqlite_snapshot_ms: float = Field(gt=0)
    short_write_baseline_ms: float = Field(gt=0)
    short_write_with_agent_ms: float = Field(gt=0)
    language_quality_passed: bool


class ReleaseChecks(ClosedModel):
    language_quality: bool
    structured_output: bool
    failure_semantics: bool
    model_calls_outside_sqlite_transactions: bool
    safety_release_gate: bool
    secrets_redacted: bool
    business_content_redacted: bool


class ReleaseThresholds(ClosedModel):
    minimum_serial_samples: int = Field(ge=1)
    minimum_free_memory_mb: float = Field(gt=0)
    language_quality_pass_rate: float = Field(gt=0, le=1)
    request_p95_ms: float = Field(gt=0)
    estimated_cost_eur_max: float = Field(gt=0)
    sqlite_snapshot_p95_ms: float = Field(gt=0)
    short_write_with_agent_p95_ms: float = Field(gt=0)
    short_write_slowdown_max: float = Field(ge=1)


class AgentReleaseReport(ClosedModel):
    schema_version: int
    target: ReleaseTarget
    profile: ReleaseProfile
    evidence: ReleaseEvidence
    measurements: ReleaseMeasurements
    checks: ReleaseChecks
    thresholds: ReleaseThresholds


class AgentReleaseStatus(ClosedModel):
    approved: bool
    blockers: list[str]
    approval_id: str | None = None


APPROVED_THRESHOLDS = ReleaseThresholds(
    minimum_serial_samples=20,
    minimum_free_memory_mb=256,
    language_quality_pass_rate=1,
    request_p95_ms=15_000,
    estimated_cost_eur_max=0.05,
    sqlite_snapshot_p95_ms=500,
    short_write_with_agent_p95_ms=200,
    short_write_slowdown_max=3,
)


def summarize_release_samples(samples: list[ReleaseSample]) -> ReleaseMeasurements:
    if not samples:
        raise ValueError("at least one release sample is required")
    if [sample.sample_index for sample in samples] != list(range(1, len(samples) + 1)):
        raise ValueError("release sample indexes must be contiguous and ordered")

    def nearest_rank_p95(values: list[float]) -> float:
        ordered = sorted(values)
        return ordered[ceil(len(ordered) * 0.95) - 1]

    return ReleaseMeasurements(
        serial_sample_count=len(samples),
        idle_peak_memory_mb=max(sample.idle_peak_memory_mb for sample in samples),
        business_peak_memory_mb=max(
            sample.business_peak_memory_mb for sample in samples
        ),
        agent_peak_memory_mb=max(sample.agent_peak_memory_mb for sample in samples),
        request_p95_ms=nearest_rank_p95([sample.request_ms for sample in samples]),
        model_stage_count_max=max(sample.model_stage_count for sample in samples),
        input_tokens_max=max(sample.input_tokens for sample in samples),
        output_tokens_max=max(sample.output_tokens for sample in samples),
        estimated_cost_eur_max=max(
            sample.estimated_cost_eur for sample in samples
        ),
        sqlite_snapshot_p95_ms=nearest_rank_p95(
            [sample.sqlite_snapshot_ms for sample in samples]
        ),
        short_write_baseline_p95_ms=nearest_rank_p95(
            [sample.short_write_baseline_ms for sample in samples]
        ),
        short_write_with_agent_p95_ms=nearest_rank_p95(
            [sample.short_write_with_agent_ms for sample in samples]
        ),
        language_quality_pass_rate=(
            sum(sample.language_quality_passed for sample in samples)
            / len(samples)
        ),
    )


def _report_blockers(report: AgentReleaseReport) -> list[str]:
    blockers: list[str] = []
    measurements = report.measurements
    thresholds = report.thresholds
    if report.schema_version != 1:
        blockers.append("unsupported release report schema")
    if thresholds != APPROVED_THRESHOLDS:
        blockers.append("release thresholds do not match the approved policy")
    if report.target.memory_limit_mb != 2048:
        blockers.append("release target is not the production 2 GB environment")
    if not report.target.single_container:
        blockers.append("release target splits the application container")
    if measurements.serial_sample_count < thresholds.minimum_serial_samples:
        blockers.append(
            "release measurements need at least "
            f"{thresholds.minimum_serial_samples} serial samples"
        )
    peak_memory = max(
        measurements.idle_peak_memory_mb,
        measurements.business_peak_memory_mb,
        measurements.agent_peak_memory_mb,
    )
    if report.target.memory_limit_mb - peak_memory < thresholds.minimum_free_memory_mb:
        blockers.append("peak memory does not leave the required safety margin")
    if measurements.request_p95_ms > thresholds.request_p95_ms:
        blockers.append("Agent request latency exceeds the release threshold")
    if measurements.estimated_cost_eur_max > thresholds.estimated_cost_eur_max:
        blockers.append("estimated model cost exceeds the release threshold")
    if measurements.sqlite_snapshot_p95_ms > thresholds.sqlite_snapshot_p95_ms:
        blockers.append("SQLite snapshot duration exceeds the release threshold")
    if (
        measurements.short_write_with_agent_p95_ms
        > thresholds.short_write_with_agent_p95_ms
    ):
        blockers.append("short write latency exceeds the release threshold")
    slowdown = (
        measurements.short_write_with_agent_p95_ms
        / measurements.short_write_baseline_p95_ms
    )
    if slowdown > thresholds.short_write_slowdown_max:
        blockers.append("Agent load slows normal short writes beyond the release threshold")
    if measurements.output_tokens_max > report.profile.max_output_tokens:
        blockers.append("measured output tokens exceed the configured limit")
    if (
        measurements.language_quality_pass_rate
        < thresholds.language_quality_pass_rate
    ):
        blockers.append("language quality does not meet the release threshold")
    check_messages = (
        ("language_quality", "language quality validation failed"),
        ("structured_output", "structured output validation failed"),
        ("failure_semantics", "provider failure semantics validation failed"),
        (
            "model_calls_outside_sqlite_transactions",
            "model calls were not proven outside SQLite transactions",
        ),
        ("safety_release_gate", "Agent safety release gate failed"),
        ("secrets_redacted", "release evidence may contain secrets"),
        ("business_content_redacted", "release evidence may contain business content"),
    )
    for field, message in check_messages:
        if not getattr(report.checks, field):
            blockers.append(message)
    return blockers


def _runtime_profile_matches(settings: Settings, profile: ReleaseProfile) -> bool:
    try:
        runtime_profile = ReleaseProfile.from_settings(settings)
    except ValidationError:
        return False
    return profile == runtime_profile


def agent_adapter_config_sha256(settings: Settings) -> str:
    payload: dict[str, object] = {"adapter": settings.model_adapter}
    if settings.model_adapter == "openai_compatible":
        primary, fallback = configured_openai_profiles(settings)
        payload.update(
            {
                "primary": primary.model_dump(mode="json", exclude={"api_key"}),
                "fallback": (
                    fallback.model_dump(mode="json", exclude={"api_key"})
                    if fallback is not None
                    else None
                ),
                "evidence_batch_limit": settings.agent_evidence_batch_limit,
            }
        )
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def agent_release_status(settings: Settings) -> AgentReleaseStatus:
    if settings.environment.lower() != "production":
        return AgentReleaseStatus(approved=True, blockers=[])
    path = settings.agent_release_report_path
    if path is None:
        return AgentReleaseStatus(
            approved=False, blockers=["release report is missing"]
        )
    if not path.is_file():
        return AgentReleaseStatus(
            approved=False, blockers=["release report is missing"]
        )
    try:
        report = AgentReleaseReport.model_validate_json(
            path.read_text(encoding="utf-8")
        )
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
        return AgentReleaseStatus(
            approved=False, blockers=["release report is invalid"]
        )
    blockers = _report_blockers(report)
    if settings.model_adapter != "openai_compatible":
        blockers.append("production release requires openai_compatible adapter")
    if not _runtime_profile_matches(settings, report.profile):
        blockers.append("runtime model profile does not match the evaluated profile")
    approval_id = None
    if not blockers:
        canonical_report = json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        approval_id = sha256(canonical_report).hexdigest()
    return AgentReleaseStatus(
        approved=not blockers,
        blockers=blockers,
        approval_id=approval_id,
    )
