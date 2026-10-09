"""Exercise the actual gate entry point with runner outcome payloads."""

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

LANES = ("api-contract", "backend-acceptance", "browser-acceptance")


@pytest.mark.parametrize("outcome", ["success", "failure", "cancelled", "skipped", "timed_out"])
def test_gate_accepts_only_success(outcome):
    for failing_lane in LANES:
        payload = {lane: {"result": outcome if lane == failing_lane else "success"} for lane in LANES}
        assert gate(json.dumps(payload)) == (0 if outcome == "success" else 1)


@pytest.mark.parametrize("payload", ["{}", "null", "[]", "broken-json", '{"api-contract":{}}'])
def test_gate_rejects_missing_or_malformed_results(payload):
    assert gate(payload) == 1


def gate(payload):
    return subprocess.run(
        [sys.executable, str(Path(__file__).resolve().parents[2] / "scripts" / "ci_gate.py")],
        env={**os.environ, "CI_NEEDS": payload}, capture_output=True, text=True, timeout=5,
    ).returncode
