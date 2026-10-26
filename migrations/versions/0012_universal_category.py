"""Add UniversalCategory table + deck.universal_category_id FK.

The admin-managed category list that groups published decks on /universal.
Decks without a category render in the per-user "Unfiled" section below.
ON DELETE SET NULL — removing a category falls its decks back to Unfiled
rather than un-publishing them.

SQLite note: batch_alter_table on `deck` is a parent-table rebuild, so
`card`, `study_session` (and transitively `study_attempt`) FKs would
cascade without PRAGMA foreign_keys=OFF. Same pattern as 0011.

Revision ID: 0012_universal_category
Revises: 0011_deck_publish
Create Date: 2026-10-26
"""
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0012_universal_category"
down_revision = "0011_deck_publish"
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
    op.create_table(
        "universal_category",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("name", name="uq_universal_category_name"),
    )
    op.create_index(
        "ix_universal_category_sort_order", "universal_category", ["sort_order"]
    )

    with _fks_off():
        with op.batch_alter_table("deck") as b:
            b.add_column(sa.Column("universal_category_id", sa.Integer(), nullable=True))
            b.create_foreign_key(
                "fk_deck_universal_category_id",
                "universal_category",
                ["universal_category_id"],
                ["id"],
                ondelete="SET NULL",
            )
            b.create_index("ix_deck_universal_category_id", ["universal_category_id"])

    # Seed German + Latin so /universal works out of the box.
    bind = op.get_bind()
    bind.execute(sa.text(
        "INSERT INTO universal_category (name, sort_order) VALUES "
        "('German vocab lists', 1), ('Latin vocab lists', 2)"
    ))


def downgrade():
    with _fks_off():
        with op.batch_alter_table("deck") as b:
            b.drop_index("ix_deck_universal_category_id")
            b.drop_constraint("fk_deck_universal_category_id", type_="foreignkey")
            b.drop_column("universal_category_id")
    op.drop_index("ix_universal_category_sort_order", table_name="universal_category")
    op.drop_table("universal_category")
