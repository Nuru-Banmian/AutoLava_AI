from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    ForeignKey,
    Integer,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

IncomeMode = Literal["legacy_total", "composed"]


class IncomeCategory(Base):
    __tablename__ = "income_categories"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    name: Mapped[str] = mapped_column(String(100))
    include_in_total: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    archived_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class StoreDailyRecord(Base):
    __tablename__ = "store_daily_records"
    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(ForeignKey("stores.id"))
    date: Mapped[date] = mapped_column(Date)
    daily_revenue: Mapped[int] = mapped_column(Integer, default=0)
    income_mode: Mapped[str] = mapped_column(String(20), default="legacy_total")
    wash_count: Mapped[int | None]
    is_open: Mapped[str] = mapped_column(String(20))
    weather: Mapped[str | None] = mapped_column(String(50))
    weather_auto: Mapped[str | None] = mapped_column(String(50))
    weather_code: Mapped[int | None]
    temperature_max: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    temperature_min: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    precipitation: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    activity: Mapped[str | None] = mapped_column(Text)
    weather_edited: Mapped[bool] = mapped_column(Boolean, default=False)
    scanned: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    items: Mapped[list["DailyIncomeItem"]] = relationship(
        cascade="all, delete-orphan", lazy="selectin"
    )
    __table_args__ = (
        UniqueConstraint("store_id", "date", name="uq_store_daily_records_store_date"),
        CheckConstraint("is_open in ('营业','休息','天气停业')", name="open_status"),
        CheckConstraint("daily_revenue >= 0", name="daily_revenue_nonnegative"),
    )


class DailyIncomeItem(Base):
    __tablename__ = "daily_income_items"
    id: Mapped[int] = mapped_column(primary_key=True)
    record_id: Mapped[int] = mapped_column(ForeignKey("store_daily_records.id", ondelete="CASCADE"))
    category_id: Mapped[int] = mapped_column(ForeignKey("income_categories.id"))
    # Defaults keep pre-snapshot fixtures and legacy audit payloads restorable.
    # Normal ledger writes always replace these with the category snapshot.
    category_name: Mapped[str] = mapped_column(String(100), default="")
    include_in_total: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(default=0)
    amount: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    __table_args__ = (
        UniqueConstraint("record_id", "category_id"),
        Index("ix_daily_income_items_record_sort", "record_id", "sort_order"),
        CheckConstraint("amount >= 0", name="amount_nonnegative"),
    )
