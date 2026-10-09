from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    JSON,
    CheckConstraint,
    ForeignKey,
    Numeric,
    String,
    Text,
    DateTime,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column
from secrets import token_hex

from app.models.base import Base


class User(Base):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    auth_identity: Mapped[str] = mapped_column(
        String(64), unique=True, default=lambda: token_hex(32)
    )
    username: Mapped[str] = mapped_column(String(80), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(10))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    manager_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    creator_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (CheckConstraint("role in ('admin','user')", name="role"),)


class LoginSession(Base):
    __tablename__ = "login_sessions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    auth_identity: Mapped[str] = mapped_column(String(64), index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(), nullable=True)


class EmployeeEditor(Base):
    __tablename__ = "employee_editors"
    employee_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    admin_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )


class Store(Base):
    __tablename__ = "stores"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(Text, default="", server_default="")
    description_revision: Mapped[int] = mapped_column(default=1, server_default="1")
    address: Mapped[str] = mapped_column(String(255))
    latitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    longitude: Mapped[Decimal] = mapped_column(Numeric(9, 6))
    timezone: Mapped[str] = mapped_column(String(64), default="Europe/Rome")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    income_items_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    income_config_revision: Mapped[int] = mapped_column(default=1, server_default="1")
    company_settlement_enabled: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0"
    )
    wash_count_enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="1")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class StoreMember(Base):
    __tablename__ = "store_members"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    __table_args__ = (UniqueConstraint("store_id", "user_id", name="uq_store_members_store_user"),)


class PermissionInitialization(Base):
    __tablename__ = "permission_initializations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    snapshot: Mapped[dict] = mapped_column(JSON)
    completed: Mapped[bool] = mapped_column(Boolean, default=False)


class DemoImport(Base):
    __tablename__ = "demo_imports"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    version: Mapped[int] = mapped_column()
    store_id: Mapped[int | None] = mapped_column(ForeignKey("stores.id", ondelete="SET NULL"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
