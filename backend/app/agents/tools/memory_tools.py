"""The curator may propose one operation; only the memory service can commit it."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryProposal(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    action: Literal["save", "duplicate", "conflict", "reject"]
    content: str = Field(min_length=1, max_length=2000)
    evidence: str = Field(min_length=1, max_length=2000)
    category: Literal["preference", "store_background"]
    target_id: str | None = None
    target_version: int | None = Field(default=None, ge=1)


MEMORY_TOOLS = [{"type": "function", "function": {
    "name": "propose_memory",
    "description": "提出一个当前用户明确指令的保存、同义去重、冲突待确认或拒绝操作。不能直接写入。",
    "parameters": MemoryProposal.model_json_schema(),
}}]
