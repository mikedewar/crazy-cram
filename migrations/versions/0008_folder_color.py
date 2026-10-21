"""Add color column to Folder; backfill with random vibrant hues.

Revision ID: 0008_folder_color
Revises: 0007_learn_section
Create Date: 2026-10-21
"""
import secrets
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0008_folder_color"
down_revision = "0007_learn_section"
branch_labels = None
depends_on = None


_PALETTE = [
    "#e63946", "#f3722c", "#f9c74f", "#43aa8b", "#2a9d8f",
    "#277da1", "#4361ee", "#7b2cbf", "#c71585", "#6a994e",
]


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
        with op.batch_alter_table("folder") as b:
            b.add_column(sa.Column("color", sa.String(length=9), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM folder WHERE color IS NULL")).fetchall()
    for (folder_id,) in rows:
        bind.execute(
            sa.text("UPDATE folder SET color = :c WHERE id = :id"),
            {"c": secrets.choice(_PALETTE), "id": folder_id},
        )


def downgrade():
    with _fks_off():
        with op.batch_alter_table("folder") as b:
            b.drop_column("color")
