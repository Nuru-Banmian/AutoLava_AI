"""Snapshot legacy permissions before explicit administrator store scoping."""

import sqlalchemy as sa
from alembic import op

revision = "0031"
down_revision = "0030"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("users") as batch:
        batch.add_column(sa.Column("manager_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_users_manager", "users", ["manager_id"], ["id"], ondelete="RESTRICT"
        )
        batch.create_index("ix_users_manager_id", ["manager_id"])
        batch.add_column(sa.Column("creator_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_users_creator", "users", ["creator_id"], ["id"], ondelete="SET NULL"
        )
        batch.create_index("ix_users_creator_id", ["creator_id"])
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
    table = op.create_table(
        "permission_initializations",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column("completed", sa.Boolean(), nullable=False),
    )
    connection = op.get_bind()
    users = [
        dict(row)
        for row in connection.execute(sa.text("SELECT id, username, role FROM users")).mappings()
    ]
    stores = list(connection.execute(sa.text("SELECT id FROM stores")).scalars())
    op.bulk_insert(
        table,
        [
            {
                "id": "admin-scope-v1",
                "snapshot": {"users": users, "stores": stores},
                "completed": False,
            }
        ],
    )
    op.create_table(
        "demo_imports",
        sa.Column("id", sa.String(40), primary_key=True),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("store_id", sa.Integer(), sa.ForeignKey("stores.id", ondelete="SET NULL")),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL")),
    )


def downgrade():
    op.drop_table("employee_editors")
    op.drop_table("demo_imports")
    op.drop_table("permission_initializations")
    with op.batch_alter_table("users") as batch:
        batch.drop_index("ix_users_creator_id")
        batch.drop_constraint("fk_users_creator", type_="foreignkey")
        batch.drop_column("creator_id")
        batch.drop_index("ix_users_manager_id")
        batch.drop_constraint("fk_users_manager", type_="foreignkey")
        batch.drop_column("manager_id")
