from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class MemorySource(BaseModel):
    id: int
    run_id: str
    message_id: int
    evidence: str
    created_at: datetime


class MemoryItem(BaseModel):
    id: str
    content: str
    category: Literal["preference", "store_background"]
    status: Literal["active", "pending_confirmation"]
    version: int
    updated_at: datetime
    index_status: Literal["pending", "ready", "failed", "not_scheduled"]
    sources: list[MemorySource]
    sources_next_before: int | None = None


class MemoryList(BaseModel):
    items: list[MemoryItem]
    next_before: str | None = None


class MemorySourceList(BaseModel):
    items: list[MemorySource]
    next_before: int | None = None
