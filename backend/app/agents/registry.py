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
    "assistant", ("read_skill", "read_skill_resource", "store_overview", "calculate"), ("store-analysis",),
)
MEMORY_CURATOR = AgentDefinition("memory_curator", ("propose_memory",), ())


def memory_capabilities():
    from app.agents.tools.memory_tools import MEMORY_TOOLS

    registered = {tool["function"]["name"]: tool for tool in MEMORY_TOOLS}
    missing = set(MEMORY_CURATOR.tools) - registered.keys()
    if missing:
        raise ValueError(f"Unknown enabled memory tools: {sorted(missing)}")
    return [registered[name] for name in MEMORY_CURATOR.tools]


def capabilities(definition=ASSISTANT):
    skills = SkillLoader(definition.skills)
    tools = default_registry(skills).bind(definition.tools)
    for name, required in skills.required_tools.items():
        missing = set(required) - tools.tools.keys()
        if missing:
            raise ValueError(f"Skill {name} requires disabled tools: {sorted(missing)}")
    return skills, tools
