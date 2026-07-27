from datetime import date, datetime, timezone
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.contracts import (
    CollectedEvidence,
    ModelMessage,
    OpenBusinessRecordsAction,
    TurnResult,
)
from app.agent.model import ModelAttempt
from app.models.agent import AgentConversation, AgentMessage

RECENT_MESSAGE_LIMIT = 12


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfirmedPeriod(ClosedModel):
    start: date
    end: date


class ConversationComparison(ClosedModel):
    period: ConfirmedPeriod
    label: str = Field(min_length=1, max_length=120)


EvidenceReferenceId = Annotated[
    str,
    StringConstraints(pattern=r"^ev_[0-9a-f]{24}$"),
]


class ConversationEvidenceReference(ClosedModel):
    reference: EvidenceReferenceId
    source: list[Literal["store_daily_records", "settlement_records"]] = Field(
        min_length=1,
        max_length=2,
    )
    queried_at: datetime
    data_version: str = Field(min_length=1, max_length=100)
    period: ConfirmedPeriod
    use_as_current_fact: Literal[False] = False


class ConversationAnalysisHypothesis(ClosedModel):
    statement: str = Field(min_length=1, max_length=500)
    status: Literal["proposed", "testing", "supported", "refuted", "unresolved"]
    evidence_references: list[EvidenceReferenceId] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def require_supported_evidence(self) -> "ConversationAnalysisHypothesis":
        if self.status in {"supported", "refuted"} and not self.evidence_references:
            raise ValueError("supported or refuted hypotheses require evidence")
        return self


class ConversationState(ClosedModel):
    investigation_goal: str | None = Field(default=None, min_length=1, max_length=2_000)
    confirmed_period: ConfirmedPeriod | None = None
    confirmed_objects: list[str] = Field(default_factory=list, max_length=20)
    evidence_references: list[ConversationEvidenceReference] = Field(
        default_factory=list,
        max_length=50,
    )
    analysis_hypotheses: list[ConversationAnalysisHypothesis] = Field(
        default_factory=list,
        max_length=8,
    )
    pending_directions: list[str] = Field(default_factory=list, max_length=8)
    metrics: list[str] = Field(default_factory=list, max_length=20)
    filters: dict[str, list[str]] = Field(default_factory=dict)
    comparison: ConversationComparison | None = None
    pending_clarifications: list[str] = Field(default_factory=list, max_length=10)


class ConversationMessageResponse(ClosedModel):
    id: int
    role: Literal["user", "assistant"]
    content: str
    action: OpenBusinessRecordsAction | None = None
    created_at: datetime


class ConversationResponse(ClosedModel):
    id: int | None
    messages: list[ConversationMessageResponse]
    state: ConversationState
    created_at: datetime | None
    updated_at: datetime | None


class AgentTurnResponse(TurnResult):
    conversation: ConversationResponse


class AgentRunResult(ClosedModel):
    turn: TurnResult
    state: ConversationState
    evidence: CollectedEvidence | None = None
    attempts: list[ModelAttempt] = Field(default_factory=list)


def empty_conversation_response() -> ConversationResponse:
    return ConversationResponse(
        id=None,
        messages=[],
        state=ConversationState(),
        created_at=None,
        updated_at=None,
    )


async def get_conversation(
    session: AsyncSession, *, user_id: int, store_id: int
) -> AgentConversation | None:
    return await session.scalar(
        select(AgentConversation).where(
            AgentConversation.user_id == user_id,
            AgentConversation.store_id == store_id,
        )
    )


async def get_conversation_by_id(
    session: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
    store_id: int,
) -> AgentConversation | None:
    return await session.scalar(
        select(AgentConversation).where(
            AgentConversation.id == conversation_id,
            AgentConversation.user_id == user_id,
            AgentConversation.store_id == store_id,
        )
    )


async def create_or_get_conversation(
    session: AsyncSession, *, user_id: int, store_id: int
) -> AgentConversation:
    conversation = await get_conversation(session, user_id=user_id, store_id=store_id)
    if conversation is not None:
        return conversation
    conversation = AgentConversation(
        user_id=user_id,
        store_id=store_id,
        state=ConversationState().model_dump(mode="json"),
    )
    session.add(conversation)
    await session.flush()
    return conversation


async def append_message(
    session: AsyncSession,
    *,
    conversation: AgentConversation,
    role: Literal["user", "assistant"],
    content: str,
    action: OpenBusinessRecordsAction | None = None,
) -> AgentMessage:
    message = AgentMessage(
        conversation_id=conversation.id,
        role=role,
        content=content,
        action=action.model_dump(mode="json") if action is not None else None,
    )
    session.add(message)
    conversation.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return message


async def recent_model_messages(
    session: AsyncSession, *, conversation_id: int
) -> list[ModelMessage]:
    newest_first = list(
        await session.scalars(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation_id)
            .order_by(AgentMessage.id.desc())
            .limit(RECENT_MESSAGE_LIMIT)
        )
    )
    return [
        ModelMessage(role=message.role, content=message.content)
        for message in reversed(newest_first)
    ]


async def conversation_response(
    session: AsyncSession, *, user_id: int, store_id: int
) -> ConversationResponse:
    conversation = await get_conversation(session, user_id=user_id, store_id=store_id)
    if conversation is None:
        return empty_conversation_response()
    messages = list(
        await session.scalars(
            select(AgentMessage)
            .where(AgentMessage.conversation_id == conversation.id)
            .order_by(AgentMessage.id)
        )
    )
    return ConversationResponse(
        id=conversation.id,
        messages=[
            ConversationMessageResponse(
                id=message.id,
                role=message.role,
                content=message.content,
                action=message.action,
                created_at=message.created_at,
            )
            for message in messages
        ],
        state=ConversationState.model_validate(conversation.state),
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
    )


async def delete_conversation(session: AsyncSession, *, user_id: int, store_id: int) -> None:
    await session.execute(
        delete(AgentConversation).where(
            AgentConversation.user_id == user_id,
            AgentConversation.store_id == store_id,
        )
    )
