from sqlalchemy import Boolean, CheckConstraint
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
