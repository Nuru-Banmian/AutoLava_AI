from datetime import date, datetime
from typing import Any

from sqlalchemy import Boolean, Date, ForeignKey, JSON, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditLog(Base):
    __tablename__ = "audit_log"
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
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
