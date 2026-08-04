from datetime import datetime
import json

from pydantic import BaseModel, Field, model_serializer


class AgentSettingsPatch(BaseModel):
    enabled: bool


class AgentMessageCreate(BaseModel):
    content: str = Field(min_length=1, max_length=4000)


class AgentMessageResponse(BaseModel):
    id: int
    role: str
    content: str
    created_at: datetime


class AgentInvestigationCardResponse(BaseModel):
    operation: str
    range_start: str | None
    range_end: str | None
    filters: list[str]
    status: str
    error_category: str | None

    @model_serializer(mode="wrap")
    def serialize(self, handler):
        payload = handler(self)
        if self.error_category is None:
            payload.pop("error_category", None)
        return payload

    @classmethod
    def from_record(cls, record) -> "AgentInvestigationCardResponse":
        return cls(
            operation=record.operation,
            range_start=record.range_start,
            range_end=record.range_end,
            filters=json.loads(record.filters_json),
            status=record.status,
            error_category=record.error_category,
        )


class AgentTurnResponse(BaseModel):
    id: int
    status: str
    error_message: str | None
    started_at: datetime
    finished_at: datetime | None
    investigation_cards: list[AgentInvestigationCardResponse] = Field(
        default_factory=list
    )


class AgentConversationResponse(BaseModel):
    conversation_id: int
    store_id: int
    store_name: str
    messages: list[AgentMessageResponse]
    latest_turn: AgentTurnResponse | None
