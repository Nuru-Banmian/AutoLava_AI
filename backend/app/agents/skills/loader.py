"""Validate enabled metadata at startup; disclose body and text resources on demand."""

from importlib.resources import files
from io import StringIO
from pathlib import PurePosixPath
import re

import yaml


class SkillError(ValueError):
    pass


class SkillLoader:
    def __init__(self, enabled: tuple[str, ...], root=None):
        self.root = root if root is not None else files("app.agents.skills")
        self.metadata = {}
        self.required_tools = {}
        for name in enabled:
            if name in self.metadata:
                raise SkillError(f"Duplicate skill: {name}")
            if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", name) or len(name) > 64:
                raise SkillError(f"Invalid skill name: {name}")
            try:
                entry = self.root.joinpath(name, "SKILL.md")
                # Read only frontmatter at startup, not the instructional body.
                with entry.open("r", encoding="utf-8") as handle:
                    lines = self._frontmatter(handle, name)
                meta = yaml.safe_load("".join(lines))
            except (OSError, yaml.YAMLError) as exc:
                raise SkillError(f"Cannot read skill metadata: {name}") from exc
            if not isinstance(meta, dict) or meta.get("name") != name:
                raise SkillError(f"Skill name must match directory: {name}")
            description = meta.get("description")
            if not isinstance(description, str) or not 1 <= len(description.strip()) <= 1024:
                raise SkillError(f"Invalid description: {name}")
            compatibility = meta.get("compatibility")
            if compatibility is not None and (
                not isinstance(compatibility, str) or not 1 <= len(compatibility) <= 500
            ):
                raise SkillError(f"Invalid compatibility: {name}")
            # Optional required capabilities are an application convention, not authorization.
            metadata = meta.get("metadata", {})
            if not isinstance(metadata, dict) or any(
                not isinstance(k, str) or not isinstance(v, str) for k, v in metadata.items()
            ):
                raise SkillError(f"Invalid metadata: {name}")
            required = metadata.get("autolava-required-capabilities", "text")
            if set(required.split()) - {"text", "references"}:
                raise SkillError(f"Unsupported required capability: {name}: {required}")
            if "allowed-tools" in meta and not isinstance(meta["allowed-tools"], str):
                raise SkillError(f"Invalid allowed-tools: {name}")
            self.metadata[name] = {"name": name, "description": description}
            self.required_tools[name] = tuple(metadata.get("autolava-required-tools", "").split())
            # Declared references can be checked without loading body or resource content.
            for path in metadata.get("autolava-references", "").split():
                self._resource(name, path)

    @staticmethod
    def _frontmatter(handle, name):
        if handle.readline().strip() != "---":
            raise SkillError(f"Missing YAML frontmatter: {name}")
        lines = []
        for line in handle:
            if line.strip() == "---":
                return lines
            lines.append(line)
            if sum(map(len, lines)) > 8192:
                raise SkillError(f"Oversized metadata: {name}")
        raise SkillError(f"Unclosed frontmatter: {name}")

    def _directory(self, name):
        if name not in self.metadata:
            raise SkillError("Skill is not enabled")
        return self.root.joinpath(name)

    def _resource(self, name, path):
        directory = self._directory(name)
        if not isinstance(path, str) or "\\" in path or ":" in path or "%" in path:
            raise SkillError("Invalid skill resource path")
        parts = path.split("/")
        if (len(parts) < 2 or parts[0] not in {"references", "assets"}
                or any(part in {"", ".", ".."} for part in parts)
                or PurePosixPath(path).suffix not in {".md", ".txt", ".json", ".csv"}):
            raise SkillError("Only relative text references/assets are supported")
        target = directory.joinpath(*parts)
        # Filesystem distributions must also reject symlink escapes.
        if hasattr(target, "resolve") and not target.resolve().is_relative_to(directory.resolve()):
            raise SkillError("Resource escapes skill directory")
        if not target.is_file():
            raise SkillError(f"Missing skill resource: {name}/{path}")
        return target

    @staticmethod
    def _read(target):
        try:
            with target.open("r", encoding="utf-8") as handle:
                content = handle.read(12001)
            if len(content) > 12000:
                raise SkillError("Skill text exceeds 12000 characters")
            return content
        except (OSError, UnicodeError) as exc:
            raise SkillError("Cannot read skill text") from exc

    def body(self, name):
        content = self._read(self._directory(name).joinpath("SKILL.md"))
        handle = StringIO(content)
        self._frontmatter(handle, name)
        return handle.read().strip()

    def resource(self, name, path):
        return self._read(self._resource(name, path))
