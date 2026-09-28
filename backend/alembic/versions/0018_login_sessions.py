"""Give existing users permanent authentication identities and persisted sessions."""

from secrets import token_hex

from alembic import op
import sqlalchemy as sa

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("auth_identity", sa.String(64), nullable=True))
    connection = op.get_bind()
    for (user_id,) in connection.execute(sa.text("SELECT id FROM users")):
        connection.execute(
            sa.text("UPDATE users SET auth_identity = :identity WHERE id = :id"),
            {"identity": token_hex(32), "id": user_id},
        )
    with op.batch_alter_table("users") as batch:
        batch.alter_column("auth_identity", nullable=False)
        batch.create_unique_constraint("uq_users_auth_identity", ["auth_identity"])
    op.create_table(
        "login_sessions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("auth_identity", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_login_sessions_auth_identity", "login_sessions", ["auth_identity"])


def downgrade() -> None:
    op.drop_index("ix_login_sessions_auth_identity", table_name="login_sessions")
    op.drop_table("login_sessions")
    with op.batch_alter_table("users") as batch:
        batch.drop_constraint("uq_users_auth_identity", type_="unique")
        batch.drop_column("auth_identity")
