import argparse
from hashlib import sha256
import json
from pathlib import Path
from pydantic import ValidationError

from app.agent.release import (
    AgentReleaseReport,
    ReleaseSample,
    agent_adapter_config_sha256,
    agent_release_status,
    summarize_release_samples,
)
from app.core.config import get_settings


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a redacted Agent release report against runtime configuration."
    )
    parser.add_argument(
        "--report",
        help="Override AUTOLAVA_AGENT_RELEASE_REPORT_PATH for this evaluation.",
    )
    parser.add_argument(
        "--schema",
        action="store_true",
        help="Print the redacted report JSON Schema without loading runtime settings.",
    )
    parser.add_argument(
        "--fingerprint",
        action="store_true",
        help="Print the non-secret runtime Adapter configuration fingerprint.",
    )
    parser.add_argument(
        "--sample-schema",
        action="store_true",
        help="Print the JSON Schema for one redacted measurement sample.",
    )
    parser.add_argument(
        "--summarize-samples",
        help="Summarize ordered redacted JSONL samples and print their SHA-256.",
    )
    arguments = parser.parse_args()
    if arguments.schema:
        print(
            json.dumps(
                AgentReleaseReport.model_json_schema(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if arguments.sample_schema:
        print(
            json.dumps(
                ReleaseSample.model_json_schema(),
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    if arguments.summarize_samples is not None:
        path = Path(arguments.summarize_samples)
        try:
            raw = path.read_bytes()
            samples = [
                ReleaseSample.model_validate_json(line) for line in raw.splitlines() if line.strip()
            ]
            measurements = summarize_release_samples(samples)
        except (OSError, UnicodeError, ValidationError, ValueError) as error:
            parser.error(str(error))
        print(
            json.dumps(
                {
                    "measurement_artifact_sha256": sha256(raw).hexdigest(),
                    "measurements": measurements.model_dump(mode="json"),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        return 0
    settings = get_settings()
    if arguments.fingerprint:
        print(agent_adapter_config_sha256(settings))
        return 0
    if arguments.report is not None:
        settings = settings.model_copy(update={"agent_release_report_path": Path(arguments.report)})
    status = agent_release_status(settings)
    print(json.dumps(status.model_dump(mode="json"), ensure_ascii=False))
    return 0 if status.approved else 1


if __name__ == "__main__":
    raise SystemExit(main())
