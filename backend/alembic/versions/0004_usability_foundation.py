"""add usability foundation income snapshots

Revision ID: 8b9c0d1e2f3a
Revises: 7a8b9c0d1e2f
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa

revision: str = "8b9c0d1e2f3a"
down_revision: str | None = "7a8b9c0d1e2f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "income_config_versions",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name=op.f("fk_income_config_versions_created_by_users"),
        ),
        sa.ForeignKeyConstraint(
            ["store_id"],
            ["stores.id"],
            name=op.f("fk_income_config_versions_store_id_stores"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_income_config_versions")),
        sa.UniqueConstraint(
            "store_id",
            "version",
            name="uq_income_config_store_version",
        ),
    )
    op.create_index(
        op.f("ix_income_config_versions_store_id"),
        "income_config_versions",
        ["store_id"],
        unique=False,
    )
    op.create_table(
        "income_config_version_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("config_version_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("include_in_total", sa.Boolean(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["category_id"],
            ["income_categories.id"],
            name=op.f("fk_income_config_version_items_category_id_income_categories"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["config_version_id"],
            ["income_config_versions.id"],
            name=op.f(
                "fk_income_config_version_items_config_version_id_income_config_versions"
            ),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_income_config_version_items")),
    )
    op.create_index(
        op.f("ix_income_config_version_items_config_version_id"),
        "income_config_version_items",
        ["config_version_id"],
        unique=False,
    )

    op.add_column("income_categories", sa.Column("archived_at", sa.DateTime(), nullable=True))
    op.add_column(
        "store_daily_records",
        sa.Column(
            "income_mode",
            sa.String(length=20),
            nullable=False,
            server_default="legacy_total",
        ),
    )
    op.add_column(
        "store_daily_records",
        sa.Column("income_config_version_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "store_daily_records",
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_foreign_key(
        op.f("fk_store_daily_records_income_config_version_id_income_config_versions"),
        "store_daily_records",
        "income_config_versions",
        ["income_config_version_id"],
        ["id"],
        ondelete="SET NULL",
    )

    op.add_column(
        "daily_income_items",
        sa.Column("category_name", sa.String(length=100), nullable=True),
    )
    op.add_column(
        "daily_income_items",
        sa.Column("include_in_total", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "daily_income_items",
        sa.Column("sort_order", sa.Integer(), nullable=True),
    )
    op.execute(
        sa.text(
            """
            UPDATE daily_income_items AS item
            INNER JOIN income_categories AS category ON category.id = item.category_id
            SET item.category_name = category.name,
                item.include_in_total = category.include_in_total,
                item.sort_order = category.sort_order
            """
        )
    )
    op.alter_column(
        "daily_income_items",
        "category_name",
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.alter_column(
        "daily_income_items",
        "include_in_total",
        existing_type=sa.Boolean(),
        nullable=False,
    )
    op.alter_column(
        "daily_income_items",
        "sort_order",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_index(
        "ix_daily_income_items_record_sort",
        "daily_income_items",
        ["record_id", "sort_order"],
        unique=False,
    )

    op.add_column("audit_log", sa.Column("snapshot_expires_at", sa.DateTime(), nullable=True))
    op.create_index(
        "ix_audit_domain_record_created",
        "audit_log",
        ["operation_domain", "record_id", "created_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_audit_domain_record_created", table_name="audit_log")
    op.drop_column("audit_log", "snapshot_expires_at")
    op.drop_index("ix_daily_income_items_record_sort", table_name="daily_income_items")
    op.drop_column("daily_income_items", "sort_order")
    op.drop_column("daily_income_items", "include_in_total")
    op.drop_column("daily_income_items", "category_name")
    op.drop_constraint(
        op.f("fk_store_daily_records_income_config_version_id_income_config_versions"),
        "store_daily_records",
        type_="foreignkey",
    )
    op.drop_column("store_daily_records", "row_version")
    op.drop_column("store_daily_records", "income_config_version_id")
    op.drop_column("store_daily_records", "income_mode")
    op.drop_column("income_categories", "archived_at")
    op.drop_index(
        op.f("ix_income_config_version_items_config_version_id"),
        table_name="income_config_version_items",
    )
    op.drop_table("income_config_version_items")
    op.drop_index(
        op.f("ix_income_config_versions_store_id"),
        table_name="income_config_versions",
    )
    op.drop_table("income_config_versions")
