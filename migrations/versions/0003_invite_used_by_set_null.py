"""invite_code.used_by → ON DELETE SET NULL.

The v0 baseline created the FK with no ON DELETE clause, so deleting a
user who has ever used an invite fails with a FK error. Keep the invite
audit row (created_at/used_at/code) but drop the link to the deleted
user — i.e. SET NULL on used_by.

SQLite has no ALTER TABLE DROP CONSTRAINT, so this uses batch_alter_table
with recreate="always" to rebuild invite_code with the desired FK.

Revision ID: 0003_invite_used_by_set_null
Revises: 0002_flashcards
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0003_invite_used_by_set_null"
down_revision = "0002_flashcards"
branch_labels = None
depends_on = None


def _target_table(name, ondelete):
    return sa.Table(
        name,
        sa.MetaData(),
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column(
            "used_by", sa.Integer(),
            sa.ForeignKey("user.id", ondelete=ondelete, name="fk_invite_code_used_by_user"),
            nullable=True,
        ),
        sa.UniqueConstraint("code", name="uq_invite_code_code"),
    )


def upgrade():
    with op.batch_alter_table(
        "invite_code",
        copy_from=_target_table("invite_code", ondelete=None),
        recreate="always",
    ) as b:
        b.drop_constraint("fk_invite_code_used_by_user", type_="foreignkey")
        b.create_foreign_key(
            "fk_invite_code_used_by_user",
            "user", ["used_by"], ["id"],
            ondelete="SET NULL",
        )


def downgrade():
    with op.batch_alter_table(
        "invite_code",
        copy_from=_target_table("invite_code", ondelete="SET NULL"),
        recreate="always",
    ) as b:
        b.drop_constraint("fk_invite_code_used_by_user", type_="foreignkey")
        b.create_foreign_key(
            "fk_invite_code_used_by_user",
            "user", ["used_by"], ["id"],
        )
