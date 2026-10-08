from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class MemoryVersion(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_version: int = Field(ge=1)


class MemoryCorrection(MemoryVersion):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    content: str = Field(min_length=1, max_length=2000)


class MemoryClear(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_revision: int = Field(ge=0)


class MemoryChange(BaseModel):
    version: int
    previous_content: str
    content: str
    created_at: datetime


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
    index_attempts: int = 0
    index_error_code: str | None = None
    sources: list[MemorySource]
    sources_next_before: int | None = None
    changes: list[MemoryChange] = Field(default_factory=list)


class MemoryList(BaseModel):
    items: list[MemoryItem]
    next_before: str | None = None
    revision: int = 0
    retrieval_status: Literal["unavailable", "processing", "failed", "available"] = "unavailable"


class MemorySourceList(BaseModel):
    items: list[MemorySource]
    next_before: int | None = None


class MemoryIndexStatus(BaseModel):
    status: Literal["unavailable", "processing", "failed", "available"]
    error_code: str | None = None
    failed: int
    pending: int


class MemoryIndexScheduled(BaseModel):
    scheduled: int
