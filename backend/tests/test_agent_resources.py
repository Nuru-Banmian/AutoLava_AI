"""Public startup/configuration seams for shipped tools and skills."""

from pathlib import Path

import pytest

from app.agents.registry import AgentDefinition, capabilities
from app.agents.skills.loader import SkillError, SkillLoader
from app.agents.tools.registry import ToolRegistry, default_registry


def skill_file(root: Path, frontmatter: str, body="BODY_NOT_LOADED_AT_STARTUP"):
    directory = root / "example"
    directory.mkdir()
    (directory / "SKILL.md").write_text(frontmatter + "\n" + body, encoding="utf-8")
    return directory


@pytest.mark.parametrize("metadata,diagnostic", [
    ("missing YAML", "frontmatter"),
    ("---\nname: [broken\n---", "metadata"),
    ("---\nname: other\ndescription: example\n---", "match directory"),
    ("---\nname: example\ndescription: ''\n---", "description"),
    ("---\nname: example\ndescription: example\nmetadata:\n  autolava-required-capabilities: shell\n---", "Unsupported required capability"),
    ("---\nname: example\ndescription: example\nmetadata:\n  autolava-references: references/missing.md\n---", "Missing skill resource"),
])
def test_invalid_enabled_skill_has_startup_diagnostic(tmp_path, metadata, diagnostic):
    skill_file(tmp_path, metadata)
    with pytest.raises(SkillError, match=diagnostic):
        SkillLoader(("example",), root=tmp_path)


def test_registry_reports_duplicate_and_unknown_references():
    registry = default_registry(SkillLoader(("store-analysis",)))
    tool = registry.tools["store_overview"]
    with pytest.raises(ValueError, match="Duplicate tool"):
        ToolRegistry([tool, tool])
    with pytest.raises(ValueError, match="Unknown enabled tools"):
        registry.bind(("missing",))
    with pytest.raises(ValueError, match="Duplicate enabled tool"):
        registry.bind(("store_overview", "store_overview"))
    with pytest.raises(SkillError, match="Duplicate skill"):
        SkillLoader(("store-analysis", "store-analysis"))
    with pytest.raises(SkillError, match="Invalid skill name"):
        SkillLoader(("../outside",))
    with pytest.raises(ValueError, match="Unknown enabled tools"):
        capabilities(AgentDefinition("new-agent", ("missing",), ()))
    with pytest.raises(ValueError, match="requires disabled tools"):
        capabilities(AgentDefinition("new-agent", ("read_skill",), ("store-analysis",)))


def test_only_enabled_metadata_is_loaded_and_authorization_is_separate(tmp_path):
    directory = skill_file(tmp_path, "---\nname: example\ndescription: example\nallowed-tools: execute_sql\n---")
    loader = SkillLoader(("example",), root=tmp_path)
    assert loader.metadata == {"example": {"name": "example", "description": "example"}}
    # Body can be read after startup; metadata's allowed-tools cannot grant a tool.
    assert loader.body("example") == "BODY_NOT_LOADED_AT_STARTUP"
    assert default_registry(loader).bind(("read_skill",)).schemas[0]["function"]["name"] == "read_skill"
    (directory / "references").mkdir()
    (directory / "references/guide.md").write_text("READ_ON_DEMAND", encoding="utf-8")
    assert loader.resource("example", "references/guide.md") == "READ_ON_DEMAND"
    with pytest.raises(SkillError, match="not enabled"):
        loader.body("disabled")


def test_symlink_resource_escape_is_denied(tmp_path):
    directory = skill_file(tmp_path, "---\nname: example\ndescription: example\n---")
    outside = tmp_path / "private.md"
    outside.write_text("PRIVATE", encoding="utf-8")
    (directory / "references").mkdir()
    try:
        (directory / "references/outside.md").symlink_to(outside)
    except OSError:
        pytest.skip("Creating symlinks requires Windows developer mode")
    loader = SkillLoader(("example",), root=tmp_path)
    with pytest.raises(SkillError, match="escapes"):
        loader.resource("example", "references/outside.md")


def test_frontmatter_inline_separator_does_not_leak_into_body(tmp_path):
    skill_file(tmp_path, '---\nname: example\ndescription: "before --- after"\n---',
               body="EXPECTED_BODY\n---\nBody separator remains")
    loader = SkillLoader(("example",), root=tmp_path)
    assert loader.body("example") == "EXPECTED_BODY\n---\nBody separator remains"
