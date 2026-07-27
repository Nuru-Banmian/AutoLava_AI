import json
from pathlib import Path
import subprocess
import sys

import yaml
from app.core.security import hash_password


ROOT = Path(__file__).resolve().parents[2]


def read(relative: str) -> str:
    return (ROOT / relative).read_text(encoding="utf-8")


def test_verification_interface_exposes_four_stable_levels() -> None:
    package = json.loads(read("package.json"))
    scripts = package["scripts"]

    assert scripts["verify:quick"] == "python scripts/verify.py quick"
    assert scripts["verify:agent"] == "python scripts/verify.py agent"
    assert scripts["verify:full"] == "python scripts/verify.py full"
    assert scripts["verify:release"] == "python scripts/verify.py release"

    verifier = read("scripts/verify.py")
    assert "AUTOLAVA_MODEL_ADAPTER" in verifier
    assert "fake" in verifier
    assert "AUTOLAVA_MODEL_API_KEY" in verifier
    assert "--strict-markers" in verifier
    assert "--strict-config" in verifier


def test_python_dependencies_are_locked_and_dev_tools_are_explicit() -> None:
    pyproject = read("backend/pyproject.toml")

    assert (ROOT / "backend/uv.lock").is_file()
    for tool in ("mypy==", "pytest==", "pytest-cov==", "pytest-xdist==", "ruff=="):
        assert tool in pyproject
    assert "[tool.mypy]" in pyproject
    assert "agent_release_gate" in pyproject
    assert '"agent:' in pyproject
    assert '"slow:' in pyproject


def test_frontend_manifest_has_no_unbounded_latest_dependencies() -> None:
    package = json.loads(read("frontend/package.json"))
    declared = {**package["dependencies"], **package["devDependencies"]}

    assert "latest" not in declared.values()
    assert package["scripts"]["check"] == "biome check ."
    assert package["scripts"]["check:ci"] == "biome ci ."


def test_ci_has_parallel_lanes_coverage_merge_and_stable_summary() -> None:
    workflow = yaml.safe_load(read(".github/workflows/ci.yml"))
    jobs = workflow["jobs"]
    required = {
        "backend-static",
        "backend-agent",
        "backend-non-agent",
        "frontend-unit-build",
        "frontend-e2e",
        "ci-summary",
    }

    assert required <= jobs.keys()
    assert jobs["ci-summary"]["name"] == "CI summary"
    assert set(jobs["ci-summary"]["needs"]) == required - {"ci-summary"}
    assert jobs["ci-summary"]["if"] == "${{ always() }}"

    rendered = read(".github/workflows/ci.yml")
    assert rendered.count("-m agent_release_gate") == 1
    assert "coverage combine" in rendered
    assert "--fail-under=85" in rendered
    assert "AUTOLAVA_MODEL_ADAPTER: fake" in rendered
    assert "AUTOLAVA_MODEL_API_KEY" not in rendered
    assert "frontend/test-results" not in rendered
    assert "redact:e2e-diagnostics" in rendered


def test_sensitive_local_browser_artifacts_are_ignored() -> None:
    ignored = read(".gitignore").splitlines()

    assert ".playwright-cli/" in ignored
    assert "output/" in ignored


def test_production_password_hash_keeps_production_cost() -> None:
    assert hash_password("production-strength-password").split("$")[2] == "12"


def test_ci_performance_requires_ten_runs_and_enforces_p95(tmp_path: Path) -> None:
    runs = [
        {
            "conclusion": "success",
            "createdAt": f"2026-07-{day:02d}T00:00:00Z",
            "updatedAt": f"2026-07-{day:02d}T00:01:00Z",
        }
        for day in range(1, 11)
    ]
    source = tmp_path / "runs.json"
    source.write_text(json.dumps(runs), encoding="utf-8")

    completed = subprocess.run(
        [sys.executable, ROOT / "scripts/ci_performance.py", source],
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert json.loads(completed.stdout)["p95_seconds"] == 60
