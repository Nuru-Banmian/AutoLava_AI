import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
    evidence_batch_limit: int = Field(gt=0)


class ReleaseMeasurements(ClosedModel):
    idle_peak_memory_mb: float = Field(ge=0)
    business_peak_memory_mb: float = Field(ge=0)
    agent_peak_memory_mb: float = Field(ge=0)
    request_p95_ms: float = Field(ge=0)
    model_stage_count_max: int = Field(ge=1)
    input_tokens_max: int = Field(ge=0)
    output_tokens_max: int = Field(ge=0)
    estimated_cost_eur_max: float = Field(ge=0)
    sqlite_snapshot_p95_ms: float = Field(ge=0)
    short_write_baseline_p95_ms: float = Field(gt=0)
    short_write_with_agent_p95_ms: float = Field(ge=0)


class ReleaseChecks(ClosedModel):
    structured_output: bool
    failure_semantics: bool
    model_calls_outside_sqlite_transactions: bool
    safety_release_gate: bool
    secrets_redacted: bool
    business_content_redacted: bool


class ReleaseThresholds(ClosedModel):
    minimum_free_memory_mb: float = Field(gt=0)
    request_p95_ms: float = Field(gt=0)
    estimated_cost_eur_max: float = Field(gt=0)
    sqlite_snapshot_p95_ms: float = Field(gt=0)
    short_write_with_agent_p95_ms: float = Field(gt=0)
    short_write_slowdown_max: float = Field(ge=1)


class AgentReleaseReport(ClosedModel):
    schema_version: int
    target: ReleaseTarget
    profile: ReleaseProfile
    measurements: ReleaseMeasurements
    checks: ReleaseChecks
    thresholds: ReleaseThresholds


class AgentReleaseStatus(ClosedModel):
    approved: bool
    blockers: list[str]


APPROVED_THRESHOLDS = ReleaseThresholds(
    minimum_free_memory_mb=256,
    request_p95_ms=15_000,
    estimated_cost_eur_max=0.05,
    sqlite_snapshot_p95_ms=500,
    short_write_with_agent_p95_ms=200,
    short_write_slowdown_max=3,
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
    check_messages = (
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
    fallback_provider = settings.fallback_model_provider if settings.fallback_model_id else None
    fallback_model = settings.fallback_model_id or None
    return profile.model_dump() == {
        "provider": settings.model_provider,
        "model": settings.model_id,
        "fallback_provider": fallback_provider,
        "fallback_model": fallback_model,
        "timeout_seconds": settings.model_timeout_seconds,
        "max_output_tokens": settings.model_max_output_tokens,
        "evidence_batch_limit": settings.agent_evidence_batch_limit,
    }


def agent_release_status(settings: Settings) -> AgentReleaseStatus:
    if settings.environment.lower() != "production":
        return AgentReleaseStatus(approved=True, blockers=[])
    raw_path = settings.agent_release_report_path.strip()
    if not raw_path:
        return AgentReleaseStatus(
            approved=False, blockers=["release report is missing"]
        )
    path = Path(raw_path)
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
    if not _runtime_profile_matches(settings, report.profile):
        blockers.append("runtime model profile does not match the evaluated profile")
    return AgentReleaseStatus(approved=not blockers, blockers=blockers)
