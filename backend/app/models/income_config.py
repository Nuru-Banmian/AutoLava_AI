from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class IncomeConfigVersion(Base):
    __tablename__ = "income_config_versions"
    __table_args__ = (
        UniqueConstraint(
            "store_id",
            "version",
            name="uq_income_config_store_version",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"),
        index=True,
    )
    version: Mapped[int]
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    items: Mapped[list["IncomeConfigVersionItem"]] = relationship(
        cascade="all, delete-orphan",
        lazy="selectin",
        order_by="IncomeConfigVersionItem.sort_order, IncomeConfigVersionItem.id",
    )


class IncomeConfigVersionItem(Base):
    __tablename__ = "income_config_version_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    config_version_id: Mapped[int] = mapped_column(
        ForeignKey("income_config_versions.id", ondelete="CASCADE"),
        index=True,
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("income_categories.id", ondelete="SET NULL"),
        nullable=True,
    )
    name: Mapped[str] = mapped_column(String(100))
    include_in_total: Mapped[bool] = mapped_column(Boolean)
    is_active: Mapped[bool] = mapped_column(Boolean)
    sort_order: Mapped[int]
