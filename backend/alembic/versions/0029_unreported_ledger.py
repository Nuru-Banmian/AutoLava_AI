"""Represent unreported days without converting unknown income to zero."""

from alembic import op
import sqlalchemy as sa

revision = "0029"
down_revision = "0028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("store_daily_records") as batch:
        batch.drop_constraint(op.f("ck_store_daily_records_open_status"), type_="check")
        batch.alter_column("daily_revenue", existing_type=sa.Integer(), nullable=True, server_default=None)
        batch.create_check_constraint("open_status", "is_open in ('营业','休息','提前休息','未统计')")
        batch.create_check_constraint(
            "statistical_values",
            "(is_open = '未统计' AND daily_revenue IS NULL AND wash_count IS NULL) OR "
            "(is_open != '未统计' AND daily_revenue IS NOT NULL AND daily_revenue >= 0)",
        )


def downgrade() -> None:
    if op.get_bind().scalar(sa.text("SELECT count(*) FROM store_daily_records WHERE is_open='未统计'")):
        raise RuntimeError("Cannot downgrade: unreported ledgers cannot be represented by the old schema")
    with op.batch_alter_table("store_daily_records") as batch:
        batch.drop_constraint(op.f("ck_store_daily_records_statistical_values"), type_="check")
        batch.drop_constraint(op.f("ck_store_daily_records_open_status"), type_="check")
        batch.alter_column("daily_revenue", existing_type=sa.Integer(), nullable=False)
        batch.create_check_constraint("open_status", "is_open in ('营业','休息','提前休息')")
