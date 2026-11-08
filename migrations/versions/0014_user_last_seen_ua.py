"""Add last_seen_ua to User.

Revision ID: 0014_user_last_seen_ua
Revises: 0013_user_last_seen
Create Date: 2026-11-08
"""
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0014_user_last_seen_ua"
down_revision = "0013_user_last_seen"
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
            b.add_column(sa.Column("last_seen_ua", sa.String(length=500), nullable=True))


def downgrade():
    with _fks_off():
        with op.batch_alter_table("user") as b:
            b.drop_column("last_seen_ua")
