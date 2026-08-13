from typing import Literal, Self

from pydantic import BaseModel, Field, field_validator, model_validator


class AgentChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(max_length=4000)

    @field_validator("content")
    @classmethod
    def normalize_content(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("message content cannot be empty")
        return normalized


class AgentChatRequest(BaseModel):
    messages: list[AgentChatMessage] = Field(min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_user_message_last(self) -> Self:
        if self.messages[-1].role != "user":
            raise ValueError("the last message must be from the user")
        return self


class AgentChatResponse(BaseModel):
    message: AgentChatMessage
