from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from app.agent_chat_types import AgentMessageRole


def normalize_message_content(value: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError("message content cannot be empty")
    return normalized


NormalizedContent = Annotated[str, AfterValidator(normalize_message_content)]
UserMessageContent = Annotated[NormalizedContent, Field(max_length=4000)]


class AgentChatMessage(BaseModel):
    role: AgentMessageRole
    content: NormalizedContent


class AgentChatRequest(BaseModel):
    content: UserMessageContent


class AgentChatResponse(BaseModel):
    message: AgentChatMessage


class AgentConversationResponse(BaseModel):
    messages: list[AgentChatMessage]
