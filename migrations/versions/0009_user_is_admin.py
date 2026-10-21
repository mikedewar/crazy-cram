"""Add is_admin column to User; mark bootstrap admin.

Revision ID: 0009_user_is_admin
Revises: 0008_folder_color
Create Date: 2026-10-21
"""
import os
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0009_user_is_admin"
down_revision = "0008_folder_color"
branch_labels = None
depends_on = None


BOOTSTRAP_ADMIN = os.environ.get("CRAZY_CRAM_BOOTSTRAP_ADMIN", "mikedewar")


@contextmanager
def _fks_off():
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        yield
        return
    raw = bind.connection.connection
    raw.isolation_level = None
    raw.execute("PRAGMA foreign_keys=OFF")
    try:
        yield
    finally:
        raw.execute("PRAGMA foreign_keys=ON")
        raw.isolation_level = ""


def upgrade():
    with _fks_off():
        with op.batch_alter_table("user") as b:
            b.add_column(
                sa.Column(
                    "is_admin",
                    sa.Boolean(),
                    nullable=False,
                    server_default="0",
                )
            )

    if BOOTSTRAP_ADMIN:
        op.get_bind().execute(
            sa.text("UPDATE user SET is_admin = 1 WHERE username = :u"),
            {"u": BOOTSTRAP_ADMIN},
        )


def downgrade():
    with _fks_off():
        with op.batch_alter_table("user") as b:
            b.drop_column("is_admin")
