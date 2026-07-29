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
    "native_tool_contract_attack",
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
REQUIRED_NATIVE_TOOL_ATTACKS = {
    "extra_field",
    "sql",
    "table",
    "field",
    "expression",
    "url",
    "role",
    "timezone",
    "multiple_groups",
    "excessive_tool_calls",
}
REQUIRED_ANSWER_ATTACKS = {
    "new_amount",
    "new_date",
    "new_metric",
    "page_action",
    "causal_claim",
}
REQUIRED_FRONTEND_COVERAGE = {
    "desktop_question_and_evidence",
    "mobile_full_screen",
    "refresh_restore",
    "store_switch_restore",
    "conversation_reset",
    "ordinary_user_hidden",
    "desktop_1440x1000",
    "mobile_390x844",
}
EXPECTED_FRONTEND_TEST_TITLES = {
    "desktop-question-and-evidence": [
        "desktop Agent workspace keeps the investigation usable and accessible"
    ],
    "mobile-full-screen": [
        "mobile home keeps a current investigation compact and continues it full-screen",
        "mobile home starts an empty investigation and opens its full-screen result",
    ],
    "refresh-switch-reset": [
        "administrator restores, switches, and permanently clears a current investigation"
    ],
    "ordinary-user-agent-hidden": ["ordinary users cannot see or invoke the Agent"],
}
EXPECTED_HTTP_ACCEPTANCE_SCENARIO_IDS = {
    "autonomous_broad_analysis",
    "data_dependent_path",
    "period_confirmation",
    "follow_up_context",
    "aggregate_drilldown",
    "prompt_injection",
    "free_evidence_answer",
    "honest_partial_result",
    "system_help_and_navigation",
    "tool_failure_recovery",
}
EXPECTED_GOLD_AMOUNTS = {
    "monthly-total-gold": {
        "daily_ledger_revenue": 240,
        "confirmed_settlement_income": 160,
        "monthly_total_revenue": 400,
    }
}


def _manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def test_release_evaluation_manifest_is_complete_and_points_to_real_tests() -> None:
    manifest = _manifest()
    assert manifest["schema_version"] == 2
    backend_cases = manifest["backend_cases"]
    frontend_cases = manifest["frontend_cases"]
    http_scenarios = manifest["http_acceptance_scenarios"]
    assert len({case["id"] for case in [*backend_cases, *frontend_cases]}) == (
        len(backend_cases) + len(frontend_cases)
    )
    assert {case["area"] for case in backend_cases} == REQUIRED_AREAS
    assert all(HAN_TEXT.search(case["question"]) for case in backend_cases)

    coverage = {item for case in backend_cases for item in case["covers"]}
    assert REQUIRED_PERIODS <= coverage
    assert REQUIRED_PROMPT_SOURCES <= coverage
    assert REQUIRED_NATIVE_TOOL_ATTACKS <= coverage
    assert REQUIRED_ANSWER_ATTACKS <= coverage
    assert {
        "dynamic_income_category",
        "missing_data",
        "company_settlement",
        "native_multi_tool",
        "data_dependent_path",
        "evidence_grounding",
        "conversation_reset",
        "ordinary_user",
        "disabled_user",
        "unauthorized_store",
        "cross_store_category",
        "model_store_or_user_identifier",
        "mid_request_authorization_change",
        "single_snapshot",
        "whole_snapshot_retry_once",
        "second_failure_discards_partial_evidence",
        "fallback_same_evidence_scope",
        "fake_native_tool_model",
        "no_real_model_secret",
    } <= coverage

    vetoes = set(manifest["veto_categories"])
    assert vetoes
    assert vetoes == {veto for case in backend_cases for veto in case["vetoes"]}
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
        case["id"]: case["gold"] for case in backend_cases if "gold_amount" in case["covers"]
    }
    assert gold_cases == EXPECTED_GOLD_AMOUNTS
    assert all(
        gold and all(type(value) in {int, float} for value in gold.values())
        for gold in gold_cases.values()
    )

    frontend_coverage = {item for case in frontend_cases for item in case["covers"]}
    assert frontend_coverage == REQUIRED_FRONTEND_COVERAGE
    for case in frontend_cases:
        assert (REPOSITORY_ROOT / "frontend" / case["test_file"]).is_file()
    assert {
        case["id"]: case["test_titles"] for case in frontend_cases
    } == EXPECTED_FRONTEND_TEST_TITLES

    assert {scenario["id"] for scenario in http_scenarios} == (
        EXPECTED_HTTP_ACCEPTANCE_SCENARIO_IDS
    )
    assert len(http_scenarios) == 10
    for scenario in http_scenarios:
        assert HAN_TEXT.search(scenario["question"])
        assert scenario["test_nodes"]
        for test_node in scenario["test_nodes"]:
            path_text, function_name = test_node.split("::", maxsplit=1)
            assert path_text.startswith("tests/api/")
            source_path = BACKEND_ROOT / path_text
            assert re.search(
                rf"^async def {re.escape(function_name)}\b",
                source_path.read_text(encoding="utf-8"),
                flags=re.MULTILINE,
            ), scenario["id"]


def test_ci_runs_the_fake_only_agent_release_veto_gate() -> None:
    workflow = yaml.safe_load(
        (REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    )
    commands = [
        step["run"] for job in workflow["jobs"].values() for step in job["steps"] if "run" in step
    ]

    assert workflow["env"]["AUTOLAVA_MODEL_ADAPTER"] == "fake"
    assert not any("MODEL_API_KEY" in key for key in workflow["env"])
    verifier = (REPOSITORY_ROOT / "scripts" / "verify.py").read_text(encoding="utf-8")
    assert commands.count("npm run verify:ci:backend-agent") == 1
    assert '"agent_release_gate"' in verifier

    frontend_commands = [
        step["run"]
        for name, job in workflow["jobs"].items()
        if name.startswith("frontend-")
        for step in job["steps"]
        if "run" in step
    ]
    package = json.loads(
        (REPOSITORY_ROOT / "frontend" / "package.json").read_text(encoding="utf-8")
    )
    assert (
        package["scripts"]["test:agent-release-manifest"]
        == "node scripts/validate-agent-release-manifest.mjs"
    )
    assert "npm run verify:ci:frontend-unit" in frontend_commands
    assert '"test:agent-release-manifest"' in verifier
