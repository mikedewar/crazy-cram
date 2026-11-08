"""Add last_seen_at and last_seen_ip to User; backfill from last_login_at.

Revision ID: 0013_user_last_seen
Revises: 0012_universal_category
Create Date: 2026-11-08
"""
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0013_user_last_seen"
down_revision = "0012_universal_category"
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
            b.add_column(sa.Column("last_seen_at", sa.DateTime(), nullable=True))
            b.add_column(sa.Column("last_seen_ip", sa.String(length=45), nullable=True))

    op.get_bind().execute(
        sa.text("UPDATE user SET last_seen_at = last_login_at WHERE last_login_at IS NOT NULL")
    )


def downgrade():
    with _fks_off():
        with op.batch_alter_table("user") as b:
            b.drop_column("last_seen_ip")
            b.drop_column("last_seen_at")
