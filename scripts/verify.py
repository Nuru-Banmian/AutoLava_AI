from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
import shutil
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"


def run(*command: str, cwd: Path = ROOT, env: dict[str, str] | None = None) -> None:
    print(f"+ {' '.join(command)}", flush=True)
    executable = shutil.which(command[0])
    if executable is None:
        raise RuntimeError(f"required command is unavailable: {command[0]}")
    subprocess.run((executable, *command[1:]), cwd=cwd, env=env, check=True)


def deterministic_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment["AUTOLAVA_MODEL_ADAPTER"] = "fake"
    environment.pop("AUTOLAVA_MODEL_API_KEY", None)
    environment.pop("AUTOLAVA_FALLBACK_MODEL_API_KEY", None)
    return environment


def sync_backend() -> None:
    run("uv", "sync", "--project", str(BACKEND), "--frozen", "--extra", "dev")


def sync_frontend() -> None:
    lockfile = FRONTEND / "package-lock.json"
    stamp = FRONTEND / "node_modules" / ".autolava-lock-sha256"
    digest = hashlib.sha256(lockfile.read_bytes()).hexdigest()
    if stamp.is_file() and stamp.read_text(encoding="ascii").strip() == digest:
        print("+ frontend dependencies match package-lock.json", flush=True)
        return
    run("npm", "ci", cwd=FRONTEND)
    stamp.write_text(digest, encoding="ascii")


def backend(*arguments: str, env: dict[str, str]) -> None:
    run("uv", "run", "--project", str(BACKEND), *arguments, cwd=BACKEND, env=env)


def quick(env: dict[str, str]) -> None:
    sync_backend()
    backend(
        "ruff",
        "format",
        "--check",
        "app/core/security.py",
        "tests/conftest.py",
        "tests/test_development_feedback.py",
        env=env,
    )
    backend("ruff", "check", ".", env=env)
    backend(
        "mypy",
        "app/agent/contracts.py",
        "app/agent/conversation.py",
        "app/agent/runtime.py",
        "app/agent/service.py",
        "app/api/routes/agent.py",
        "app/api/routes/agent_admin.py",
        env=env,
    )
    backend(
        "pytest",
        "--strict-markers",
        "--strict-config",
        "-q",
        "tests/agent/test_contracts.py",
        "tests/test_development_feedback.py",
        env=env,
    )


def agent(env: dict[str, str]) -> None:
    sync_backend()
    sync_frontend()
    backend(
        "pytest",
        "--strict-markers",
        "--strict-config",
        "-q",
        "tests/agent",
        "tests/api/test_agent.py",
        "tests/api/test_agent_grouping.py",
        "tests/api/test_agent_observability.py",
        "tests/api/test_agent_periods.py",
        "tests/api/test_agent_prompt_injection_sources.py",
        "tests/api/test_agent_wash_count_evidence.py",
        env=env,
    )
    run("npm", "test", "--", "--run", "src/components/AgentPanel.test.tsx", cwd=FRONTEND, env=env)
    run("npm", "run", "test:agent-release-manifest", cwd=FRONTEND, env=env)


def full(env: dict[str, str]) -> None:
    sync_backend()
    sync_frontend()
    backend(
        "pytest",
        "--strict-markers",
        "--strict-config",
        "-n",
        "auto",
        "--dist",
        "loadscope",
        "--cov=app",
        "--cov-fail-under=85",
        env=env,
    )
    run("npm", "run", "check:ci", cwd=FRONTEND, env=env)
    run("npm", "test", cwd=FRONTEND, env=env)
    run("npm", "run", "build", cwd=FRONTEND, env=env)
    run("npm", "run", "test:e2e", cwd=FRONTEND, env=env)


def release(env: dict[str, str]) -> None:
    sync_backend()
    sync_frontend()
    backend(
        "pytest",
        "--strict-markers",
        "--strict-config",
        "-m",
        "agent_release_gate",
        env=env,
    )
    run("npm", "run", "test:agent-release-manifest", cwd=FRONTEND, env=env)
    run(
        "npm",
        "run",
        "test:e2e",
        "--",
        "tests/agent-conversation.spec.ts",
        cwd=FRONTEND,
        env=env,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="Run an AutoLava verification level.")
    parser.add_argument("level", choices=("quick", "agent", "full", "release"))
    args = parser.parse_args()
    globals()[args.level](deterministic_environment())


if __name__ == "__main__":
    main()
