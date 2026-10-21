"""Add last_login_at column to User.

Revision ID: 0010_user_last_login_at
Revises: 0009_user_is_admin
Create Date: 2026-10-21
"""
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0010_user_last_login_at"
down_revision = "0009_user_is_admin"
branch_labels = None
depends_on = None


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
            b.add_column(sa.Column("last_login_at", sa.DateTime(), nullable=True))


def downgrade():
    with _fks_off():
        with op.batch_alter_table("user") as b:
            b.drop_column("last_login_at")
