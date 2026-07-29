from datetime import datetime

from pydantic import BaseModel, Field


class AgentSettingsPatch(BaseModel):
    enabled: bool


class AgentMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class AgentMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class AgentTurnResponse(BaseModel):
    id: int
    status: str
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None


class AgentConversationResponse(BaseModel):
    conversation_id: int
    store_id: int
    store_name: str
    messages: list[AgentMessageResponse]
    latest_turn: AgentTurnResponse | None
