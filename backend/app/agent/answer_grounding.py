from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from decimal import Decimal, InvalidOperation
import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.agent.contracts import EvidenceBundle, EvidenceMetric, EvidencePeriodResult
from app.services.weather import WEATHER_LABELS


_ISO_DATE = re.compile(r"(?<!\d)(20\d{2}|21\d{2}|2200)-(\d{1,2})-(\d{1,2})(?!\d)")
_CHINESE_DATE = re.compile(
    r"(?<!\d)(20\d{2}|21\d{2}|2200)\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*[日号]"
)
_CHINESE_MONTH = re.compile(r"(?<!\d)(20\d{2}|21\d{2}|2200)\s*年\s*(\d{1,2})\s*月")
_CHINESE_MONTH_WITHOUT_YEAR = re.compile(r"(?<![\d年])(\d{1,2})\s*月")
_MONEY = re.compile(
    r"(?<![\d.])(-?\d+(?:[.,]\d+)?)\s*(欧元|美元|人民币|英镑|EUR|USD|CNY|GBP|€|\$|¥|£)",
    re.IGNORECASE,
)
_DAY_COUNT = re.compile(r"(?<![\d.])(-?\d+(?:[.,]\d+)?)\s*(?:个)?(?:经营)?日(?!期)")
_PERCENTAGE = re.compile(r"(?<![\d.])(-?\d+(?:[.,]\d+)?)\s*(?:%|％|百分比)")
_CROSS_SCOPE = re.compile(r"另一个门店|其他门店|其它门店|全部门店|所有门店")
_UNSUPPORTED_METRIC = re.compile(r"利润|毛利|净利|客单价")
_PHENOMENON = re.compile(r"天气|暴雨|降雨|下雨|降雪|高温|低温|事件|公共假期|节假日|假期|促销")
_CAUSAL = re.compile(r"导致|致使|使得|造成|引起|归因于|因为|由于|证明(?:了)?")
_CAUSAL_DISCLAIMER = re.compile(
    r"不能证明(?:是)?(?:原因|因果)?|无法证明(?:是)?(?:原因|因果)?|"
    r"不代表(?:是)?(?:原因|因果)|并非(?:是)?.{0,12}(?:原因|因果)"
)
_OPERATING_SUBJECT = re.compile(
    r"门店|经营|生意|收入|营业额|结算|开票|洗车|客流|销量|业绩|成本|支出|金额|"
    r"比率|比例|天气|事件|假期|节假日|促销|利润"
)
_UNCERTAINTY = re.compile(
    r"可能|也许|假设|待检验|待验证|无法确认|不能确认|未知|尚不清楚|不可用|"
    r"不能证明|无法证明|不代表|并非|相关(?:性)?"
)
_OPERATING_JUDGMENT = re.compile(
    r"主要(?:来自|因为|由于)?|表现(?:良好|不佳|较好|较差)|"
    r"异常|改善|恶化|增长|下降|最佳|最差|旺盛|低迷|很好|上佳"
)
_NEGATED_VERIFIED_FACT = re.compile(r"不是|并非|不等于|并不|未达到|没有达到")
_UNSUPPORTED_FACT_COMPARISON = re.compile(
    r"低于|高于|少于|多于|大于|小于|不超过|至少|至多|超过|未满|不足"
)
_EXACT_VALUE_CONNECTOR = re.compile(
    r"\s*(?:为|是|等于|达到|合计(?:为)?|共计(?:为)?|总计(?:为)?|：|:)\s*"
)
_PERCENTAGE_CHANGE_CONNECTOR = re.compile(r"\s*(?:增长|增加|上升|提高|下降|减少|降低|下滑)\s*")
_INCREASE = re.compile(r"增长|增加|上升|提高")
_DECREASE = re.compile(r"下降|减少|降低|下滑")
_METRIC_FIELDS = {
    "月度总收入": "monthly_total_revenue",
    "总收入": "monthly_total_revenue",
    "每日台账营业额": "daily_ledger_revenue",
    "台账营业额": "daily_ledger_revenue",
    "已确认公司结算收入": "confirmed_settlement_income",
    "公司结算收入": "confirmed_settlement_income",
    "经营日": "operating_days",
}


class NativeAnswerClaim(BaseModel):
    """Machine-checkable metadata beside freely authored answer prose."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    statement: str = Field(min_length=1, max_length=1_000)
    status: Literal["verified_fact", "analysis_hypothesis", "unknown"]
    evidence_references: list[str] = Field(default_factory=list, max_length=20)
    metric: EvidenceMetric | None = None
    period: EvidencePeriodResult | None = None
    value: Decimal | None = None
    unit: Literal["EUR", "day", "car", "EUR/car", "EUR/operating_day", "percent"] | None = None
    relationship: Literal["none", "correlation", "causation"] = "none"

    @model_validator(mode="after")
    def require_auditable_fact_shape(self) -> "NativeAnswerClaim":
        if any(
            re.fullmatch(r"ev_[0-9a-f]{24}", reference) is None
            for reference in self.evidence_references
        ):
            raise ValueError("invalid evidence reference")
        if self.status == "verified_fact" and (
            not self.evidence_references
            or self.metric is None
            or self.period is None
            or self.value is None
            or self.unit is None
        ):
            raise ValueError("verified facts require evidence, metric, period, value, and unit")
        return self


def answer_is_grounded(
    answer: str,
    evidence: Sequence[EvidenceBundle],
    claims: Sequence[NativeAnswerClaim] = (),
    evidence_by_reference: Mapping[str, EvidenceBundle] | None = None,
) -> bool:
    """Validate high-impact claims without constraining the answer's prose layout."""

    evidence_by_reference = evidence_by_reference or {}
    if not evidence:
        return _answer_without_evidence_is_safe(answer, claims)
    if not _claims_are_grounded(answer, claims, evidence_by_reference):
        return False
    if not _key_literals_are_claimed(answer, claims):
        return False
    if not _operating_statements_are_claimed(answer, claims):
        return False
    if _CROSS_SCOPE.search(answer) or _UNSUPPORTED_METRIC.search(answer):
        return False
    if not _dates_are_supported(answer, evidence):
        return False
    if not _quantities_are_supported(answer, evidence):
        return False
    for clause in _clauses(answer):
        if _is_unsupported_causal_statement(clause):
            return False
        if _OPERATING_JUDGMENT.search(clause) and not _judgment_is_supported(clause, claims):
            return False
    return True


def _answer_without_evidence_is_safe(
    answer: str,
    claims: Sequence[NativeAnswerClaim],
) -> bool:
    if not claims:
        return False
    if any(claim.status == "verified_fact" for claim in claims):
        return False
    if any(
        claim.statement not in answer
        or claim.relationship == "causation"
        or not _UNCERTAINTY.search(claim.statement)
        or not _claim_status_is_visible(claim)
        for claim in claims
    ):
        return False
    if _contains_business_fact(answer) or not _operating_statements_are_claimed(answer, claims):
        return False
    for clause in _clauses(answer):
        if _is_unsupported_causal_statement(clause):
            return False
        if (
            _OPERATING_JUDGMENT.search(clause) or _OPERATING_SUBJECT.search(clause)
        ) and not _UNCERTAINTY.search(clause):
            return False
    return True


def _is_unsupported_causal_statement(sentence: str) -> bool:
    return bool(
        _OPERATING_SUBJECT.search(sentence)
        and _CAUSAL.search(sentence)
        and not _CAUSAL_DISCLAIMER.search(sentence)
    )


def _claims_are_grounded(
    answer: str,
    claims: Sequence[NativeAnswerClaim],
    evidence_by_reference: Mapping[str, EvidenceBundle],
) -> bool:
    for claim in claims:
        if claim.statement not in answer:
            return False
        if claim.relationship == "causation":
            return False
        if not _claim_status_is_visible(claim):
            return False
        if claim.status != "verified_fact":
            continue
        if _NEGATED_VERIFIED_FACT.search(claim.statement):
            return False
        if _UNSUPPORTED_FACT_COMPARISON.search(claim.statement):
            return False
        if _contains_phenomenon(claim.statement):
            return False
        referenced = [
            evidence_by_reference.get(reference) for reference in claim.evidence_references
        ]
        if any(bundle is None for bundle in referenced):
            return False
        if not any(
            bundle is not None
            and bundle.metric == claim.metric
            and bundle.period == claim.period
            and _claim_value_is_supported(claim, bundle)
            and _claim_literals_match_metadata(claim)
            for bundle in referenced
        ):
            return False
    return True


def _claim_value_is_supported(
    claim: NativeAnswerClaim,
    bundle: EvidenceBundle,
) -> bool:
    if claim.unit == "percent":
        return bool(
            bundle.comparison is not None
            and bundle.comparison.percentage_status == "available"
            and bundle.comparison.percentage_change is not None
            and claim.value == Decimal(str(bundle.comparison.percentage_change))
        )
    return bool(
        bundle.unit == claim.unit
        and claim.metric is not None
        and claim.value
        in _field_values(
            bundle.result.model_dump(mode="python"),
            claim.metric.value,
        )
    )


def _claim_literals_match_metadata(claim: NativeAnswerClaim) -> bool:
    if claim.period is None or claim.value is None or claim.unit is None:
        return False
    for pattern in (_ISO_DATE, _CHINESE_DATE):
        for match in pattern.finditer(claim.statement):
            try:
                claimed_date = date(*(int(part) for part in match.groups()))
            except ValueError:
                return False
            if not claim.period.start <= claimed_date <= claim.period.end:
                return False
    for match in _CHINESE_MONTH.finditer(claim.statement):
        year, month = (int(part) for part in match.groups())
        if (year, month) != (claim.period.start.year, claim.period.start.month):
            return False
    full_month_spans = [match.span() for match in _CHINESE_MONTH.finditer(claim.statement)]
    for match in _CHINESE_MONTH_WITHOUT_YEAR.finditer(claim.statement):
        if any(_overlaps(match.span(), span) for span in full_month_spans):
            continue
        if int(match.group(1)) != claim.period.start.month:
            return False
    money_values = [_decimal(match.group(1)) for match in _MONEY.finditer(claim.statement)]
    percentage_values = [
        _decimal(match.group(1)) for match in _PERCENTAGE.finditer(claim.statement)
    ]
    day_values = [_decimal(match.group(1)) for match in _DAY_COUNT.finditer(claim.statement)]
    metric_is_visible = any(
        field == claim.metric.value and term in claim.statement
        for term, field in _METRIC_FIELDS.items()
    )
    if not metric_is_visible:
        return False
    if claim.unit in {"EUR", "day"} and not _has_exact_value_relation(claim):
        return False
    if claim.unit == "percent" and not _has_percentage_change_relation(claim):
        return False
    if claim.unit == "EUR" and (
        not money_values
        or any(value != claim.value for value in money_values)
        or percentage_values
        or day_values
    ):
        return False
    if claim.unit == "percent" and (
        not percentage_values
        or any(value != _visible_percentage_value(claim) for value in percentage_values)
        or money_values
        or day_values
    ):
        return False
    if claim.unit == "day" and (
        not day_values
        or any(value != claim.value for value in day_values)
        or money_values
        or percentage_values
    ):
        return False
    return True


def _has_exact_value_relation(claim: NativeAnswerClaim) -> bool:
    value_pattern = _MONEY if claim.unit == "EUR" else _DAY_COUNT
    return _has_metric_value_relation(claim, value_pattern, _EXACT_VALUE_CONNECTOR)


def _has_percentage_change_relation(claim: NativeAnswerClaim) -> bool:
    return _has_metric_value_relation(claim, _PERCENTAGE, _PERCENTAGE_CHANGE_CONNECTOR)


def _has_metric_value_relation(
    claim: NativeAnswerClaim,
    value_pattern: re.Pattern[str],
    connector_pattern: re.Pattern[str],
) -> bool:
    if claim.metric is None:
        return False
    metric_matches = [
        match
        for term, field in _METRIC_FIELDS.items()
        if field == claim.metric.value
        for match in re.finditer(re.escape(term), claim.statement)
    ]
    return any(
        metric_match.end() <= value_match.start()
        and connector_pattern.fullmatch(claim.statement[metric_match.end() : value_match.start()])
        and not claim.statement[value_match.end() :].strip()
        for metric_match in metric_matches
        for value_match in value_pattern.finditer(claim.statement)
    )


def _visible_percentage_value(claim: NativeAnswerClaim) -> Decimal | None:
    if claim.value is None:
        return None
    if _DECREASE.search(claim.statement):
        return abs(claim.value) if claim.value < 0 else None
    if _INCREASE.search(claim.statement):
        return abs(claim.value) if claim.value > 0 else None
    return claim.value


def _claim_status_is_visible(claim: NativeAnswerClaim) -> bool:
    if claim.status == "analysis_hypothesis":
        return bool(re.search(r"假设|可能|也许|待检验|待验证", claim.statement))
    if claim.status == "unknown":
        return bool(re.search(r"未知|无法确认|不能确认|尚不清楚|不可用", claim.statement))
    return True


def _key_literals_are_claimed(
    answer: str,
    claims: Sequence[NativeAnswerClaim],
) -> bool:
    claim_spans = [
        (match.start(), match.end())
        for claim in claims
        for match in re.finditer(re.escape(claim.statement), answer)
    ]
    key_spans = [
        match.span()
        for pattern in (
            _ISO_DATE,
            _CHINESE_DATE,
            _CHINESE_MONTH,
            _CHINESE_MONTH_WITHOUT_YEAR,
            _MONEY,
            _DAY_COUNT,
            _PERCENTAGE,
        )
        for match in pattern.finditer(answer)
    ]
    return all(any(_overlaps(span, claim_span) for claim_span in claim_spans) for span in key_spans)


def _operating_statements_are_claimed(
    answer: str,
    claims: Sequence[NativeAnswerClaim],
) -> bool:
    for clause in _clauses(answer):
        if not (
            _OPERATING_SUBJECT.search(clause)
            or _OPERATING_JUDGMENT.search(clause)
            or _contains_phenomenon(clause)
        ):
            continue
        if not any(
            _normalized_statement(claim.statement) == _normalized_statement(clause)
            for claim in claims
        ):
            return False
    return True


def _contains_business_fact(answer: str) -> bool:
    return bool(
        _MONEY.search(answer)
        or _DAY_COUNT.search(answer)
        or _PERCENTAGE.search(answer)
        or _UNSUPPORTED_METRIC.search(answer)
        or _CROSS_SCOPE.search(answer)
    )


def _contains_phenomenon(statement: str) -> bool:
    return bool(
        _PHENOMENON.search(statement)
        or any(label in statement for label in WEATHER_LABELS.values())
    )


def _dates_are_supported(answer: str, evidence: Sequence[EvidenceBundle]) -> bool:
    periods = [(bundle.period.start, bundle.period.end) for bundle in evidence]
    date_spans: list[tuple[int, int]] = []
    for pattern in (_ISO_DATE, _CHINESE_DATE):
        for match in pattern.finditer(answer):
            try:
                claimed = date(*(int(part) for part in match.groups()))
            except ValueError:
                return False
            if not any(start <= claimed <= end for start, end in periods):
                return False
            date_spans.append(match.span())
    for match in _CHINESE_MONTH.finditer(answer):
        if any(_overlaps(match.span(), span) for span in date_spans):
            continue
        year, month = (int(part) for part in match.groups())
        if not any(start.year == year and start.month == month for start, _ in periods):
            return False
    full_month_spans = [match.span() for match in _CHINESE_MONTH.finditer(answer)]
    for match in _CHINESE_MONTH_WITHOUT_YEAR.finditer(answer):
        if any(_overlaps(match.span(), span) for span in full_month_spans):
            continue
        month = int(match.group(1))
        if not any(start.month == month for start, _ in periods):
            return False
    return True


def _quantities_are_supported(answer: str, evidence: Sequence[EvidenceBundle]) -> bool:
    facts_by_unit: dict[str, set[Decimal]] = {}
    for bundle in evidence:
        facts_by_unit.setdefault(bundle.unit, set()).update(_numeric_values(bundle.result))

    for clause in _clauses(answer):
        for match in _MONEY.finditer(clause):
            value = _decimal(match.group(1))
            currency = match.group(2).casefold()
            if value is None or currency not in {"欧元", "eur", "€"}:
                return False
            metric_field = _nearest_metric_field(clause[: match.start()])
            supported_values = (
                _values_for_field(evidence, metric_field)
                if metric_field is not None
                else facts_by_unit.get("EUR", set())
            )
            if value not in supported_values:
                return False
    calendar_date_spans = [
        match.span() for pattern in (_ISO_DATE, _CHINESE_DATE) for match in pattern.finditer(answer)
    ]
    for match in _DAY_COUNT.finditer(answer):
        if any(_overlaps(match.span(), span) for span in calendar_date_spans):
            continue
        value = _decimal(match.group(1))
        if value is None or value not in facts_by_unit.get("day", set()):
            return False
    supported_percentages = {
        abs(Decimal(str(bundle.comparison.percentage_change)))
        for bundle in evidence
        if bundle.comparison is not None
        and bundle.comparison.percentage_status == "available"
        and bundle.comparison.percentage_change is not None
    }
    for match in _PERCENTAGE.finditer(answer):
        value = _decimal(match.group(1))
        if value is None or value not in supported_percentages:
            return False
    return True


def _numeric_values(value: object) -> set[Decimal]:
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, dict):
        return set().union(*(_numeric_values(item) for item in value.values()), set())
    if isinstance(value, (list, tuple)):
        return set().union(*(_numeric_values(item) for item in value), set())
    if isinstance(value, bool) or value is None:
        return set()
    if isinstance(value, (int, float, Decimal)):
        return {Decimal(str(value))}
    return set()


def _values_for_field(
    evidence: Sequence[EvidenceBundle],
    field: str,
) -> set[Decimal]:
    return set().union(
        *(_field_values(bundle.result.model_dump(mode="python"), field) for bundle in evidence),
        set(),
    )


def _field_values(value: object, field: str) -> set[Decimal]:
    if isinstance(value, dict):
        matched = _numeric_values(value[field]) if field in value else set()
        return matched.union(*(_field_values(item, field) for item in value.values()), set())
    if isinstance(value, (list, tuple)):
        return set().union(*(_field_values(item, field) for item in value), set())
    return set()


def _nearest_metric_field(prefix: str) -> str | None:
    matches = (
        (prefix.rfind(term), field) for term, field in _METRIC_FIELDS.items() if term in prefix
    )
    return next((field for position, field in sorted(matches, reverse=True) if position >= 0), None)


def _judgment_is_supported(
    clause: str,
    claims: Sequence[NativeAnswerClaim],
) -> bool:
    matching = [
        claim
        for claim in claims
        if _normalized_statement(claim.statement) == _normalized_statement(clause)
    ]
    if any(
        claim.status in {"analysis_hypothesis", "unknown"} and _UNCERTAINTY.search(clause)
        for claim in matching
    ):
        return True
    return any(
        claim.status == "verified_fact"
        and claim.unit in {"EUR", "percent"}
        and (
            (_INCREASE.search(clause) and claim.value is not None and claim.value > 0)
            or (_DECREASE.search(clause) and claim.value is not None and claim.value < 0)
        )
        for claim in matching
    )


def _decimal(raw: str) -> Decimal | None:
    try:
        return Decimal(raw.replace(",", "."))
    except InvalidOperation:
        return None


def _sentences(answer: str) -> Iterable[str]:
    return (part for part in re.split(r"(?<=[。！？!?；;\n])", answer) if part.strip())


def _clauses(answer: str) -> Iterable[str]:
    return (
        part
        for part in re.split(
            r"(?<=[。！？!?；;，,\n])|(?:而且|并且|同时|另外|此外|以及|不过|但是|但|却|且)",
            answer,
        )
        if part.strip()
    )


def _normalized_statement(statement: str) -> str:
    return statement.strip(" \t\r\n。！？!?；;，,:：")


def _overlaps(left: tuple[int, int], right: tuple[int, int]) -> bool:
    return left[0] < right[1] and right[0] < left[1]
