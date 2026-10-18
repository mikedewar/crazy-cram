"""Add color column to Deck; backfill existing rows with random pastels.

Revision ID: 0005_deck_color
Revises: 0004_folders
Create Date: 2026-09-27
"""
import secrets

from alembic import op
import sqlalchemy as sa


revision = "0005_deck_color"
down_revision = "0004_folders"
branch_labels = None
depends_on = None


_PALETTE = [
    "#ffd6d6", "#ffe8c2", "#fff4b8", "#dff5c5", "#c8ecd6",
    "#c8e6f2", "#d6dcf5", "#e8d1f2", "#f5cfe1", "#e8dfd0",
]


def upgrade():
    with op.batch_alter_table("deck") as b:
        b.add_column(sa.Column("color", sa.String(length=9), nullable=True))

    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT id FROM deck WHERE color IS NULL")).fetchall()
    for (deck_id,) in rows:
        bind.execute(
            sa.text("UPDATE deck SET color = :c WHERE id = :id"),
            {"c": secrets.choice(_PALETTE), "id": deck_id},
        )


def downgrade():
    with op.batch_alter_table("deck") as b:
        b.drop_column("color")
