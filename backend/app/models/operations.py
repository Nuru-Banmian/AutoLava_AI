from datetime import datetime

from sqlalchemy import JSON, Boolean, ForeignKey, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

LEGACY_TIMESTAMP_CONTRACT = "legacy_unknown"
UTC_TIMESTAMP_CONTRACT = "utc_v1"


class DailyBriefing(Base):
    __tablename__ = "daily_briefings"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    card_type: Mapped[str] = mapped_column(String(20))
    content: Mapped[str] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    generated_at: Mapped[datetime] = mapped_column(server_default=func.now())
    timestamp_contract: Mapped[str] = mapped_column(
        String(24), default=LEGACY_TIMESTAMP_CONTRACT, server_default=LEGACY_TIMESTAMP_CONTRACT
    )
    __table_args__ = (
        UniqueConstraint("store_id", "card_type", name="uq_daily_briefings_store_card"),
    )


class ScheduledTaskLog(Base):
    __tablename__ = "scheduled_task_logs"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"))
    task_type: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(default=0)
    started_at: Mapped[datetime]
    finished_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    timestamp_contract: Mapped[str] = mapped_column(
        String(24), default=LEGACY_TIMESTAMP_CONTRACT, server_default=LEGACY_TIMESTAMP_CONTRACT
    )


class SystemAlert(Base):
    __tablename__ = "system_alerts"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"))
    alert_type: Mapped[str] = mapped_column(String(60))
    level: Mapped[str] = mapped_column(String(20))
    message: Mapped[str] = mapped_column(Text)
    is_resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    resolved_at: Mapped[datetime | None]
    timestamp_contract: Mapped[str] = mapped_column(
        String(24), default=LEGACY_TIMESTAMP_CONTRACT, server_default=LEGACY_TIMESTAMP_CONTRACT
    )
