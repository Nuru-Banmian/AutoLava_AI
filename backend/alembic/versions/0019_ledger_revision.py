"""Give daily ledger records non-reusable identities and revisions."""

from uuid import uuid4

from alembic import op
import sqlalchemy as sa

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("store_daily_records", sa.Column("identity", sa.String(36), nullable=True))
    op.add_column(
        "store_daily_records",
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
    )
    connection = op.get_bind()
    for (record_id,) in connection.execute(sa.text("SELECT id FROM store_daily_records")):
        connection.execute(
            sa.text("UPDATE store_daily_records SET identity = :identity WHERE id = :id"),
            {"identity": str(uuid4()), "id": record_id},
        )
    with op.batch_alter_table("store_daily_records") as batch:
        batch.alter_column("identity", nullable=False)
        batch.create_unique_constraint("uq_store_daily_records_identity", ["identity"])


def downgrade() -> None:
    with op.batch_alter_table("store_daily_records") as batch:
        batch.drop_constraint("uq_store_daily_records_identity", type_="unique")
        batch.drop_column("identity")
        batch.drop_column("revision")
