import json
from pathlib import Path
import re

import yaml


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = BACKEND_ROOT.parent
MANIFEST_PATH = Path(__file__).with_name("agent_release_cases.json")
HAN_TEXT = re.compile(r"[\u4e00-\u9fff]")

REQUIRED_AREAS = {
    "business_question",
    "conversation",
    "permission_attack",
    "prompt_injection",
    "evidence_plan_attack",
    "answer_validation",
    "sqlite_consistency",
    "model_recovery",
    "ci_safety",
}
REQUIRED_PERIODS = {
    "current_month",
    "previous_month",
    "previous_month_to_date",
    "calendar_month",
    "calendar_year",
    "exact_date",
    "custom_date_range",
}
REQUIRED_PROMPT_SOURCES = {
    "user_question",
    "raw_event",
    "income_category_name",
    "settlement_company_name",
    "business_evidence",
}
REQUIRED_PLAN_ATTACKS = {
    "extra_field",
    "sql",
    "table",
    "field",
    "expression",
    "url",
    "role",
    "timezone",
    "multiple_groups",
    "excessive_requests",
}
REQUIRED_ANSWER_ATTACKS = {
    "new_amount",
    "new_date",
    "new_metric",
    "page_action",
    "causal_claim",
}
REQUIRED_FRONTEND_COVERAGE = {
    "administrator_query",
    "refresh_restore",
    "user_triggered_business_records",
    "prefilled_months",
    "conversation_reset",
    "ordinary_user_hidden",
}
EXPECTED_FRONTEND_TEST_TITLES = {
    "admin-complete-agent-flow": [
        "administrator restores, switches, and permanently resets per-store conversations"
    ],
    "business-records-action": [
        "desktop business records action is user-triggered, prefills months, and does not overflow",
        "mobile business records action is user-triggered, prefills months, and does not overflow",
    ],
    "ordinary-user-agent-hidden": [
        "ordinary users cannot see or invoke the Agent"
    ],
}
EXPECTED_GOLD_AMOUNTS = {
    "monthly-total-gold": {
        "daily_ledger_revenue": 240,
        "confirmed_settlement_income": 160,
        "monthly_total_revenue": 400,
    },
    "revenue-analysis": {
        "current_daily_ledger_revenue": 160,
        "current_confirmed_settlement_income": 0,
        "current_total_revenue": 160,
        "comparison_daily_ledger_revenue": 100,
        "comparison_confirmed_settlement_income": 0,
        "comparison_total_revenue": 100,
        "total_revenue_change": 60,
        "daily_ledger_revenue_change": 60,
        "confirmed_settlement_income_change": 0,
    },
}


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_release_evaluation_manifest_is_complete_and_points_to_real_tests() -> None:
    manifest = _manifest()
    assert manifest["schema_version"] == 1
    backend_cases = manifest["backend_cases"]
    frontend_cases = manifest["frontend_cases"]
    assert len({case["id"] for case in [*backend_cases, *frontend_cases]}) == (
        len(backend_cases) + len(frontend_cases)
    )
    assert {case["area"] for case in backend_cases} == REQUIRED_AREAS
    assert all(HAN_TEXT.search(case["question"]) for case in backend_cases)

    coverage = {
        item
        for case in backend_cases
        for item in case["covers"]
    }
    assert REQUIRED_PERIODS <= coverage
    assert REQUIRED_PROMPT_SOURCES <= coverage
    assert REQUIRED_PLAN_ATTACKS <= coverage
    assert REQUIRED_ANSWER_ATTACKS <= coverage
    assert {
        "dynamic_income_category",
        "missing_data",
        "company_settlement",
        "revenue_analysis",
        "conversation_reset",
        "ordinary_user",
        "disabled_user",
        "unauthorized_store",
        "cross_store_category",
        "model_store_or_user_identifier",
        "mid_request_authorization_change",
        "single_snapshot",
        "whole_batch_retry_once",
        "second_failure_discards_partial_evidence",
        "fallback_same_evidence_scope",
        "fake_model_adapter",
        "no_real_model_secret",
    } <= coverage

    vetoes = set(manifest["veto_categories"])
    assert vetoes
    assert vetoes == {
        veto
        for case in backend_cases
        for veto in case["vetoes"]
    }
    for case in backend_cases:
        assert case["vetoes"]
        path_text, function_name = case["test_node"].split("::", maxsplit=1)
        source_path = BACKEND_ROOT / path_text
        assert source_path.is_file(), case["id"]
        assert re.search(
            rf"^(?:async )?def {re.escape(function_name)}\b",
            source_path.read_text(encoding="utf-8"),
            flags=re.MULTILINE,
        ), case["id"]

    gold_cases = {
        case["id"]: case["gold"]
        for case in backend_cases
        if "gold_amount" in case["covers"]
    }
    assert gold_cases == EXPECTED_GOLD_AMOUNTS
    assert all(
        gold and all(type(value) in {int, float} for value in gold.values())
        for gold in gold_cases.values()
    )

    frontend_coverage = {
        item
        for case in frontend_cases
        for item in case["covers"]
    }
    assert frontend_coverage == REQUIRED_FRONTEND_COVERAGE
    for case in frontend_cases:
        assert (REPOSITORY_ROOT / "frontend" / case["test_file"]).is_file()
    assert {
        case["id"]: case["test_titles"] for case in frontend_cases
    } == EXPECTED_FRONTEND_TEST_TITLES


def test_ci_runs_the_fake_only_agent_release_veto_gate() -> None:
    workflow = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
            encoding="utf-8"
        )
    )
    backend = workflow["jobs"]["backend"]
    commands = [step["run"] for step in backend["steps"] if "run" in step]

    assert backend["env"]["AUTOLAVA_MODEL_ADAPTER"] == "fake"
    assert not any("MODEL_API_KEY" in key for key in backend["env"])
    assert any(
        "pytest -m agent_release_gate --strict-markers" in command
        for command in commands
    )

    frontend = workflow["jobs"]["frontend"]
    frontend_commands = [
        step["run"] for step in frontend["steps"] if "run" in step
    ]
    package = json.loads(
        (REPOSITORY_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    assert (
        package["scripts"]["test:agent-release-manifest"]
        == "node scripts/validate-agent-release-manifest.mjs"
    )
    assert "npm run test:agent-release-manifest" in frontend_commands
