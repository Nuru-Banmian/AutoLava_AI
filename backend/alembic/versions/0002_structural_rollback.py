"""structural rollback linkage

Revision ID: 6f7c8d9e0a1b
Revises: f2558fedb4c7
Create Date: 2026-07-13 23:30:00.000000

"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "6f7c8d9e0a1b"
down_revision: str | None = "f2558fedb4c7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add an indexed, one-to-one structural link from a rollback to its target audit."""
    op.add_column("audit_log", sa.Column("rollback_of_audit_id", sa.Integer(), nullable=True))
    op.create_unique_constraint(
        op.f("uq_audit_log_rollback_of_audit_id"),
        "audit_log",
        ["rollback_of_audit_id"],
    )
    op.create_foreign_key(
        op.f("fk_audit_log_rollback_of_audit_id_audit_log"),
        "audit_log",
        "audit_log",
        ["rollback_of_audit_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    """Remove structural rollback linkage."""
    op.drop_constraint(
        op.f("fk_audit_log_rollback_of_audit_id_audit_log"),
        "audit_log",
        type_="foreignkey",
    )
    op.drop_constraint(
        op.f("uq_audit_log_rollback_of_audit_id"),
        "audit_log",
        type_="unique",
    )
    op.drop_column("audit_log", "rollback_of_audit_id")
