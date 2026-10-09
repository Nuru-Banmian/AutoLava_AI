"""Complete employee editor schema for databases that ran the early 0028."""

import sqlalchemy as sa
from alembic import op

revision = "0032"
down_revision = "0031"
branch_labels = None
depends_on = None


def upgrade():
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    added_creator = "creator_id" not in {c["name"] for c in inspector.get_columns("users")}
    if added_creator:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("creator_id", sa.Integer(), nullable=True))
            batch.create_foreign_key(
                "fk_users_creator", "users", ["creator_id"], ["id"], ondelete="SET NULL"
            )
            batch.create_index("ix_users_creator_id", ["creator_id"])
        # Early 0028 had no creator history. Preserve its current responsible
        # administrator as the compatibility creator, without resetting scope.
        connection.execute(
            sa.text(
                "UPDATE users SET creator_id=manager_id "
                "WHERE role='user' AND manager_id IS NOT NULL "
                "AND EXISTS (SELECT 1 FROM permission_initializations "
                "WHERE id='admin-scope-v1' AND completed=1)"
            )
        )
    if not inspector.has_table("employee_editors"):
        op.create_table(
            "employee_editors",
            sa.Column(
                "employee_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
            sa.Column(
                "admin_id",
                sa.Integer(),
                sa.ForeignKey("users.id", ondelete="CASCADE"),
                primary_key=True,
            ),
        )


def downgrade():
    # Both objects belong to the final 0028 schema. Keep them when returning to
    # that revision; its downgrade owns removal and existing grants must survive.
    pass
