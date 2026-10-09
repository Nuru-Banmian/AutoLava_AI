"""Fail closed unless every required PR CI lane finished successfully."""

import json
import os
import sys

REQUIRED = {"api-contract", "backend-acceptance", "browser-acceptance"}


def main():
    try:
        results = json.loads(os.environ["CI_NEEDS"])
        valid = (isinstance(results, dict) and results.keys() == REQUIRED
                 and all(isinstance(lane, dict) and lane.get("result") == "success"
                         for lane in results.values()))
    except (KeyError, ValueError):
        valid = False
    if not valid:
        print("CI gate failed: all required lanes must finish with success", file=sys.stderr)
        return 1
    print("CI gate passed: all required lanes succeeded")
    return 0


if __name__ == "__main__":
    sys.exit(main())
