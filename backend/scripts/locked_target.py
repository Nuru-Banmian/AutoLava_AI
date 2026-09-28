"""Select production requirements whose markers apply to this build Python."""

import sys
import tomllib
from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name


def main() -> None:
    selected: dict[str, str] = {}
    project = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))["project"]
    selected[canonicalize_name(project["name"])] = project["version"]
    for line in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        requirement = Requirement(line)
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        versions = [part.version for part in requirement.specifier if part.operator == "=="]
        if len(versions) != 1:
            raise ValueError(f"Expected one locked version for {requirement.name}")
        selected[canonicalize_name(requirement.name)] = versions[0]
    for name, version in sorted(selected.items()):
        print(f"{name}=={version}")


if __name__ == "__main__":
    main()
