from __future__ import annotations

import argparse
from datetime import datetime
import json
import math
from pathlib import Path


def duration_seconds(run: dict[str, str]) -> float:
    started = datetime.fromisoformat(run["createdAt"].replace("Z", "+00:00"))
    finished = datetime.fromisoformat(run["updatedAt"].replace("Z", "+00:00"))
    return (finished - started).total_seconds()


def percentile_95(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * 0.95) - 1)]


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Validate the latest ten successful CI run durations."
    )
    parser.add_argument("runs_json", type=Path)
    parser.add_argument("--target-seconds", type=float, default=120)
    args = parser.parse_args()

    runs = json.loads(args.runs_json.read_text(encoding="utf-8"))
    successful = [run for run in runs if run.get("conclusion") == "success"][:10]
    if len(successful) != 10:
        raise SystemExit("exactly ten successful runs are required")

    durations = [duration_seconds(run) for run in successful]
    p95 = percentile_95(durations)
    print(json.dumps({"runs": 10, "durations_seconds": durations, "p95_seconds": p95}))
    if p95 > args.target_seconds:
        raise SystemExit(f"CI p95 {p95:.1f}s exceeds target {args.target_seconds:.1f}s")


if __name__ == "__main__":
    main()
