from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

AGENT_SYSTEM_SETTINGS_ID = 1


class AgentSystemSettings(Base):
    __tablename__ = "agent_system_settings"

    id: Mapped[int] = mapped_column(
        primary_key=True,
        default=AGENT_SYSTEM_SETTINGS_ID,
    )
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default="0",
    )

    __table_args__ = (
        CheckConstraint("id = 1", name="singleton"),
    )


class AgentConversation(Base):
    __tablename__ = "agent_conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"),
    )
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"),
    )
    context_summary: Mapped[str] = mapped_column(
        Text,
        default="",
        server_default="",
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(),
        onupdate=func.now(),
    )

    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "store_id",
            name="uq_agent_conversations_user_store",
        ),
    )


class AgentMessage(Base):
    __tablename__ = "agent_messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
    )
    role: Mapped[str] = mapped_column(String(16))
    content: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    __table_args__ = (
        CheckConstraint(
            "role in ('user','assistant')",
            name="role",
        ),
    )


class AgentTurn(Base):
    __tablename__ = "agent_turns"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(
        ForeignKey("agent_conversations.id", ondelete="CASCADE"),
        index=True,
    )
    user_message_id: Mapped[int] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="CASCADE"),
    )
    assistant_message_id: Mapped[int | None] = mapped_column(
        ForeignKey("agent_messages.id", ondelete="SET NULL"),
        nullable=True,
    )
    status: Mapped[str] = mapped_column(String(16))
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime] = mapped_column(
        DateTime,
        server_default=func.now(),
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "status in ('running','completed','failed','interrupted')",
            name="status",
        ),
    )
