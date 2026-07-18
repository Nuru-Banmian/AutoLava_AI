from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, Index, JSON, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (
        UniqueConstraint("rollback_of_audit_id"),
        Index(
            "ix_audit_domain_record_created",
            "operation_domain",
            "record_id",
            "created_at",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    operation_domain: Mapped[str] = mapped_column(String(30))
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id"))
    record_id: Mapped[int | None]
    record_date: Mapped[date | None] = mapped_column(Date)
    operation_type: Mapped[str] = mapped_column(String(20))
    operation_source: Mapped[str] = mapped_column(String(20))
    operator_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    before_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    after_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text)
    requires_approval: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)
    rollbackable: Mapped[bool] = mapped_column(Boolean, default=True)
    rollback_of_audit_id: Mapped[int | None] = mapped_column(
        ForeignKey("audit_log.id", ondelete="CASCADE")
    )
    snapshot_expires_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
