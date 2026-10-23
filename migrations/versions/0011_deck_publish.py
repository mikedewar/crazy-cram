"""Add publish/share columns to Deck.

Columns:
  published_at DATETIME NULL — NULL = personal; UTC timestamp = published to Universal.
  source_deck_id INTEGER NULL FK deck.id ON DELETE SET NULL — points at the
    original published deck for decks created via /universal/<id>/add.
    SET NULL so deleting the original leaves downstream copies intact.

SQLite note: batch_alter_table on `deck` is a parent-table rebuild — `card`,
`study_session`, and (transitively) `study_attempt` all FK into deck.
With PRAGMA foreign_keys=ON the implicit drop fires those cascades.
Every batch_alter_table runs inside _fks_off() to avoid data loss.

Revision ID: 0011_deck_publish
Revises: 0010_user_last_login_at
Create Date: 2026-10-23
"""
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0011_deck_publish"
down_revision = "0010_user_last_login_at"
branch_labels = None
depends_on = None


@contextmanager
def _fks_off():
    """Disable SQLite foreign_keys around a batch rebuild.

    PRAGMA foreign_keys is a no-op inside a transaction, so we reach down to
    the raw DBAPI connection and set it there.
    """
    bind = op.get_bind()
    if bind.dialect.name != "sqlite":
        yield
        return
    raw = bind.connection.connection  # DBAPI sqlite3.Connection
    raw.isolation_level = None  # autocommit
    raw.execute("PRAGMA foreign_keys=OFF")
    try:
        yield
    finally:
        raw.execute("PRAGMA foreign_keys=ON")
        raw.isolation_level = ""


def upgrade():
    with _fks_off():
        with op.batch_alter_table("deck") as b:
            b.add_column(sa.Column("published_at", sa.DateTime(), nullable=True))
            b.add_column(sa.Column("source_deck_id", sa.Integer(), nullable=True))
            b.create_foreign_key(
                "fk_deck_source_deck_id",
                "deck",
                ["source_deck_id"],
                ["id"],
                ondelete="SET NULL",
            )
            b.create_index("ix_deck_published_at", ["published_at"])
            b.create_index("ix_deck_source_deck_id", ["source_deck_id"])


def downgrade():
    with _fks_off():
        with op.batch_alter_table("deck") as b:
            b.drop_index("ix_deck_source_deck_id")
            b.drop_index("ix_deck_published_at")
            b.drop_constraint("fk_deck_source_deck_id", type_="foreignkey")
            b.drop_column("source_deck_id")
            b.drop_column("published_at")
