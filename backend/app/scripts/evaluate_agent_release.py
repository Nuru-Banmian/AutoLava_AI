import argparse
import json

from app.agent.release import (
    AgentReleaseReport,
    agent_adapter_config_sha256,
    agent_release_status,
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
    settings = get_settings()
    if arguments.fingerprint:
        print(agent_adapter_config_sha256(settings))
        return 0
    if arguments.report is not None:
        settings = settings.model_copy(
            update={"agent_release_report_path": arguments.report}
        )
    status = agent_release_status(settings)
    print(json.dumps(status.model_dump(mode="json"), ensure_ascii=False))
    return 0 if status.approved else 1


if __name__ == "__main__":
    raise SystemExit(main())
