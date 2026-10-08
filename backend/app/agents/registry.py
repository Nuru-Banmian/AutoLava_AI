"""Agent definitions select capabilities explicitly; registration grants no identity."""

from dataclasses import dataclass

from app.agents.skills.loader import SkillLoader
from app.agents.tools.registry import default_registry


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    tools: tuple[str, ...]
    skills: tuple[str, ...]


ASSISTANT = AgentDefinition(
    "assistant", ("read_skill", "read_skill_resource", "store_overview"), ("store-analysis",),
)


def capabilities(definition=ASSISTANT):
    skills = SkillLoader(definition.skills)
    tools = default_registry(skills).bind(definition.tools)
    for name, required in skills.required_tools.items():
        missing = set(required) - tools.tools.keys()
        if missing:
            raise ValueError(f"Skill {name} requires disabled tools: {sorted(missing)}")
    return skills, tools
