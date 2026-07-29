from datetime import datetime
from hashlib import sha256
import json
from math import ceil
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from app.agent.factory import configured_openai_profiles
from app.core.config import Settings


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReleaseTarget(ClosedModel):
    memory_limit_mb: int = Field(gt=0)
    single_container: bool
    application_processes: int = Field(ge=1)
    application_workers: int = Field(ge=1)
    database_engine: str = Field(min_length=1)


class ReleaseProfile(ClosedModel):
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    timeout_seconds: float = Field(gt=0)
    max_output_tokens: int = Field(gt=0)
    input_cost_per_million: float = Field(gt=0)
    output_cost_per_million: float = Field(gt=0)
    max_model_calls: int = Field(ge=1)
    max_tool_calls: int = Field(ge=1)
    max_total_tokens: int = Field(ge=1)
    max_cost_eur: float = Field(gt=0)
    retry_attempts: int = Field(ge=0)
    adapter_config_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")

    @classmethod
    def from_settings(cls, settings: Settings) -> "ReleaseProfile":
        fallback_provider = settings.fallback_model_provider if settings.fallback_model_id else None
        return cls(
            provider=settings.model_provider,
            model=settings.model_id,
            fallback_provider=fallback_provider,
            fallback_model=settings.fallback_model_id or None,
            timeout_seconds=settings.model_timeout_seconds,
            max_output_tokens=settings.model_max_output_tokens,
            input_cost_per_million=settings.model_input_cost_per_million,
            output_cost_per_million=settings.model_output_cost_per_million,
            max_model_calls=settings.agent_investigation_max_model_calls,
            max_tool_calls=settings.agent_investigation_max_tool_calls,
            max_total_tokens=settings.agent_investigation_max_tokens,
            max_cost_eur=settings.agent_investigation_max_cost_eur,
            retry_attempts=settings.agent_investigation_retry_attempts,
            adapter_config_sha256=agent_adapter_config_sha256(settings),
        )


class ReleaseEvidence(ClosedModel):
    collected_at: datetime
    collector_version: Literal["agent-release-v2"]
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
    tool_call_count_max: int = Field(ge=0)
    agent_request_concurrency_max: int = Field(ge=1)
    input_tokens_max: int = Field(gt=0)
    output_tokens_max: int = Field(gt=0)
    total_tokens_max: int = Field(gt=0)
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
    tool_call_count: int = Field(ge=0)
    agent_request_concurrency: int = Field(ge=1)
    input_tokens: int = Field(gt=0)
    output_tokens: int = Field(gt=0)
    total_tokens: int = Field(gt=0)
    estimated_cost_eur: float = Field(gt=0)
    sqlite_snapshot_ms: float = Field(gt=0)
    short_write_baseline_ms: float = Field(gt=0)
    short_write_with_agent_ms: float = Field(gt=0)
    language_quality_passed: bool

    @model_validator(mode="after")
    def require_consistent_total_tokens(self) -> "ReleaseSample":
        if self.total_tokens != self.input_tokens + self.output_tokens:
            raise ValueError("total tokens must equal input plus output tokens")
        return self


AdapterCaseName = Literal[
    "structured_output",
    "native_tool_calling",
    "parallel_tool_calls",
    "tool_result_continuation",
    "natural_answer",
    "usage_metrics",
    "timeout",
    "rate_limit",
    "server_error",
    "authentication",
    "balance",
    "invalid_output",
    "safety_release_gate",
    "secrets_redacted",
    "business_content_redacted",
]


class AdapterCaseResult(ClosedModel):
    case: AdapterCaseName
    passed: bool


class AdapterCasesArtifact(ClosedModel):
    cases: list[AdapterCaseResult] = Field(min_length=15, max_length=15)


class MonotonicInterval(ClosedModel):
    started_ms: float = Field(ge=0)
    ended_ms: float = Field(gt=0)

    @model_validator(mode="after")
    def require_positive_duration(self) -> "MonotonicInterval":
        if self.ended_ms <= self.started_ms:
            raise ValueError("trace interval must have positive duration")
        return self

    def overlaps(self, other: "MonotonicInterval") -> bool:
        return self.started_ms < other.ended_ms and other.started_ms < self.ended_ms


class TransactionTraceSample(ClosedModel):
    sample_index: int = Field(ge=1)
    evidence_stage: MonotonicInterval
    model_calls: list[MonotonicInterval] = Field(min_length=1)
    sqlite_snapshots: list[MonotonicInterval] = Field(min_length=1)
    short_write_locks: list[MonotonicInterval] = Field(min_length=1)

    @model_validator(mode="after")
    def require_safe_model_and_bounded_short_write_intervals(
        self,
    ) -> "TransactionTraceSample":
        protected_intervals = [*self.sqlite_snapshots, *self.short_write_locks]
        if any(
            model_call.overlaps(protected)
            for model_call in self.model_calls
            for protected in protected_intervals
        ):
            raise ValueError("model calls must not overlap SQLite snapshots or write locks")
        if not any(
            write_lock.overlaps(self.evidence_stage) for write_lock in self.short_write_locks
        ):
            raise ValueError("a bounded short write must overlap the evidence stage")
        return self


class ReleaseChecks(ClosedModel):
    language_quality: bool
    structured_output: bool
    native_adapter_probe: bool
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
    approved_report_sha256: str | None = None


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
MEASUREMENT_ARTIFACT = "samples.jsonl"
ADAPTER_CASES_ARTIFACT = "adapter-cases.json"
TRANSACTION_TRACE_ARTIFACT = "transaction-trace.jsonl"
FAILURE_CASES = {
    "timeout",
    "rate_limit",
    "server_error",
    "authentication",
    "balance",
    "invalid_output",
}


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
        business_peak_memory_mb=max(sample.business_peak_memory_mb for sample in samples),
        agent_peak_memory_mb=max(sample.agent_peak_memory_mb for sample in samples),
        request_p95_ms=nearest_rank_p95([sample.request_ms for sample in samples]),
        model_stage_count_max=max(sample.model_stage_count for sample in samples),
        tool_call_count_max=max(sample.tool_call_count for sample in samples),
        agent_request_concurrency_max=max(sample.agent_request_concurrency for sample in samples),
        input_tokens_max=max(sample.input_tokens for sample in samples),
        output_tokens_max=max(sample.output_tokens for sample in samples),
        total_tokens_max=max(sample.total_tokens for sample in samples),
        estimated_cost_eur_max=max(sample.estimated_cost_eur for sample in samples),
        sqlite_snapshot_p95_ms=nearest_rank_p95([sample.sqlite_snapshot_ms for sample in samples]),
        short_write_baseline_p95_ms=nearest_rank_p95(
            [sample.short_write_baseline_ms for sample in samples]
        ),
        short_write_with_agent_p95_ms=nearest_rank_p95(
            [sample.short_write_with_agent_ms for sample in samples]
        ),
        language_quality_pass_rate=(
            sum(sample.language_quality_passed for sample in samples) / len(samples)
        ),
    )


def _report_blockers(report: AgentReleaseReport) -> list[str]:
    blockers: list[str] = []
    measurements = report.measurements
    thresholds = report.thresholds
    if report.schema_version != 2:
        blockers.append("unsupported release report schema")
    if thresholds != APPROVED_THRESHOLDS:
        blockers.append("release thresholds do not match the approved policy")
    if report.target.memory_limit_mb != 2048:
        blockers.append("release target is not the production 2 GB environment")
    if not report.target.single_container:
        blockers.append("release target splits the application container")
    if report.target.application_processes != 1:
        blockers.append("release target does not use one application process")
    if report.target.application_workers != 1:
        blockers.append("release target does not use one application worker")
    if report.target.database_engine != "sqlite":
        blockers.append("release target does not use SQLite")
    if measurements.serial_sample_count < thresholds.minimum_serial_samples:
        blockers.append(
            f"release measurements need at least {thresholds.minimum_serial_samples} serial samples"
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
    if measurements.estimated_cost_eur_max > report.profile.max_cost_eur:
        blockers.append("measured model cost exceeds the configured investigation limit")
    if measurements.sqlite_snapshot_p95_ms > thresholds.sqlite_snapshot_p95_ms:
        blockers.append("SQLite snapshot duration exceeds the release threshold")
    if measurements.short_write_with_agent_p95_ms > thresholds.short_write_with_agent_p95_ms:
        blockers.append("short write latency exceeds the release threshold")
    slowdown = measurements.short_write_with_agent_p95_ms / measurements.short_write_baseline_p95_ms
    if slowdown > thresholds.short_write_slowdown_max:
        blockers.append("Agent load slows normal short writes beyond the release threshold")
    if measurements.output_tokens_max > report.profile.max_output_tokens:
        blockers.append("measured output tokens exceed the configured limit")
    if measurements.total_tokens_max > report.profile.max_total_tokens:
        blockers.append("measured total tokens exceed the configured investigation limit")
    if measurements.model_stage_count_max > report.profile.max_model_calls:
        blockers.append("measured model calls exceed the configured limit")
    if measurements.tool_call_count_max > report.profile.max_tool_calls:
        blockers.append("measured tool calls exceed the configured limit")
    if measurements.agent_request_concurrency_max != 1:
        blockers.append("release measurements are not from serial Agent requests")
    if measurements.language_quality_pass_rate < thresholds.language_quality_pass_rate:
        blockers.append("language quality does not meet the release threshold")
    check_messages = (
        ("language_quality", "language quality validation failed"),
        ("structured_output", "structured output validation failed"),
        ("native_adapter_probe", "native model Adapter capability probe failed"),
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


def _release_artifact_blockers(
    report: AgentReleaseReport,
    report_path: Path,
) -> list[str]:
    artifact_specs = (
        (
            MEASUREMENT_ARTIFACT,
            report.evidence.measurement_artifact_sha256,
        ),
        (
            ADAPTER_CASES_ARTIFACT,
            report.evidence.adapter_cases_artifact_sha256,
        ),
        (
            TRANSACTION_TRACE_ARTIFACT,
            report.evidence.transaction_trace_artifact_sha256,
        ),
    )
    raw_artifacts: dict[str, bytes] = {}
    blockers: list[str] = []
    for filename, expected_sha256 in artifact_specs:
        try:
            raw = (report_path.parent / filename).read_bytes()
        except OSError:
            blockers.append(f"release evidence artifact is missing: {filename}")
            continue
        if sha256(raw).hexdigest() != expected_sha256:
            blockers.append(f"release evidence artifact hash does not match: {filename}")
            continue
        raw_artifacts[filename] = raw
    if blockers:
        return blockers

    try:
        samples = [
            ReleaseSample.model_validate_json(line)
            for line in raw_artifacts[MEASUREMENT_ARTIFACT].splitlines()
            if line.strip()
        ]
        measured = summarize_release_samples(samples)
        adapter_artifact = AdapterCasesArtifact.model_validate_json(
            raw_artifacts[ADAPTER_CASES_ARTIFACT]
        )
        transaction_samples = [
            TransactionTraceSample.model_validate_json(line)
            for line in raw_artifacts[TRANSACTION_TRACE_ARTIFACT].splitlines()
            if line.strip()
        ]
    except (UnicodeError, json.JSONDecodeError, ValidationError, ValueError):
        return ["release evidence artifact is invalid"]

    if measured != report.measurements:
        blockers.append("release measurements do not match the sample artifact")
    case_results = {item.case: item.passed for item in adapter_artifact.cases}
    if len(case_results) != len(adapter_artifact.cases):
        blockers.append("release Adapter cases contain duplicates")
        return blockers
    expected_cases = set(AdapterCaseName.__args__)
    if set(case_results) != expected_cases:
        blockers.append("release Adapter cases are incomplete")
        return blockers
    expected_indexes = list(range(1, len(transaction_samples) + 1))
    if (
        not transaction_samples
        or [item.sample_index for item in transaction_samples] != expected_indexes
        or len(transaction_samples) != len(samples)
    ):
        blockers.append("release transaction traces do not match the sample sequence")
        return blockers
    if any(
        len(trace.model_calls) != sample.model_stage_count
        for trace, sample in zip(transaction_samples, samples, strict=True)
    ):
        blockers.append("release transaction traces do not cover every model call")
        return blockers
    derived_checks = ReleaseChecks(
        language_quality=all(sample.language_quality_passed for sample in samples),
        structured_output=case_results["structured_output"],
        native_adapter_probe=all(
            case_results[name]
            for name in (
                "native_tool_calling",
                "parallel_tool_calls",
                "tool_result_continuation",
                "natural_answer",
                "usage_metrics",
            )
        ),
        failure_semantics=all(case_results[name] for name in FAILURE_CASES),
        model_calls_outside_sqlite_transactions=True,
        safety_release_gate=case_results["safety_release_gate"],
        secrets_redacted=case_results["secrets_redacted"],
        business_content_redacted=case_results["business_content_redacted"],
    )
    if derived_checks != report.checks:
        blockers.append("release checks do not match the evidence artifacts")
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
        return AgentReleaseStatus(approved=False, blockers=["release report is missing"])
    if not path.is_file():
        return AgentReleaseStatus(approved=False, blockers=["release report is missing"])
    try:
        report = AgentReleaseReport.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError):
        return AgentReleaseStatus(approved=False, blockers=["release report is invalid"])
    blockers = _report_blockers(report)
    blockers.extend(_release_artifact_blockers(report, path))
    if settings.model_adapter != "openai_compatible":
        blockers.append("production release requires openai_compatible adapter")
    if not _runtime_profile_matches(settings, report.profile):
        blockers.append("runtime model profile does not match the evaluated profile")
    if settings.agent_runtime_image_digest != report.evidence.container_image_digest:
        blockers.append("runtime image does not match the evaluated image")
    approved_report_sha256 = None
    if not blockers:
        canonical_report = json.dumps(
            report.model_dump(mode="json"),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        approved_report_sha256 = sha256(canonical_report).hexdigest()
    return AgentReleaseStatus(
        approved=not blockers,
        blockers=blockers,
        approved_report_sha256=approved_report_sha256,
    )
