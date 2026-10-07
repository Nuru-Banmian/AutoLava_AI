from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ChatGeneration(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation: int = Field(ge=0)


class ChatSubmit(ChatGeneration):
    content: str = Field(min_length=1, max_length=6000)
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")

    @field_validator("content")
    @classmethod
    def nonempty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("消息不能为空")
        return value.strip()


class ChatMessage(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    role: Literal["user", "assistant"]
    content: str


class ChatRun(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    generation: int
    request_id: str | None
    status: Literal["running", "completed", "failed"]
    output: str
    error_code: str | None
    model: str
    calls: int
    usage: dict[str, int] | None


class ChatConversation(BaseModel):
    generation: int = 0
    messages: list[ChatMessage]
    run: ChatRun | None
    next_before: int | None = None
