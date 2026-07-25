"""unify ledger operating status"""

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CONSTRAINT_NAME = "ck_store_daily_records_open_status"


def _replace_status_constraint(*, old_status: str, new_status: str) -> None:
    op.execute("PRAGMA foreign_keys=OFF")
    op.execute("PRAGMA ignore_check_constraints=ON")
    op.execute(
        f"UPDATE store_daily_records SET is_open = '{new_status}' "
        f"WHERE is_open = '{old_status}'"
    )
    with op.batch_alter_table("store_daily_records", recreate="always") as batch_op:
        batch_op.drop_constraint(op.f(_CONSTRAINT_NAME), type_="check")
        batch_op.create_check_constraint(
            op.f(_CONSTRAINT_NAME),
            f"is_open in ('营业','休息','{new_status}')",
        )
    op.execute("PRAGMA ignore_check_constraints=OFF")
    op.execute("PRAGMA foreign_keys=ON")


def upgrade() -> None:
    _replace_status_constraint(old_status="天气停业", new_status="提前休息")
    op.execute(
        """
        DELETE FROM daily_briefings
        WHERE content LIKE '%天气停业%'
           OR CAST(payload AS TEXT) LIKE '%weather_closed%'
        """
    )


def downgrade() -> None:
    _replace_status_constraint(old_status="提前休息", new_status="天气停业")
