"""Add mode column to StudySession.

Values: 'written' (type the answer) | 'mc' (pick a radio option).
All existing sessions become 'written' retroactively.

SQLite note: batch_alter_table rebuilds the table via copy-and-rename.
With PRAGMA foreign_keys=ON (as the app sets per-connection) the drop
of the parent study_session fires study_attempt.session_id ON DELETE
CASCADE and wipes every attempt row. We disable FKs for the duration
of each batch_alter_table and restore them after.

Revision ID: 0006_study_mode
Revises: 0005_deck_color
Create Date: 2026-10-18
"""
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0006_study_mode"
down_revision = "0005_deck_color"
branch_labels = None
depends_on = None


@contextmanager
def _fks_off():
    """Disable SQLite foreign_keys around a batch rebuild.

    PRAGMA foreign_keys is a no-op inside a transaction, so we reach
    down to the raw DBAPI connection and set it there. SQLAlchemy's
    bound connection is still in its own transaction, but SQLite reads
    the pragma off the underlying connection handle.
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
        raw.isolation_level = ""  # restore SQLAlchemy default


def upgrade():
    # Two-step so existing rows aren't left with NULL under NOT NULL.
    with _fks_off():
        with op.batch_alter_table("study_session") as b:
            b.add_column(sa.Column("mode", sa.String(length=16), nullable=True))
    op.execute("UPDATE study_session SET mode = 'written' WHERE mode IS NULL")
    with _fks_off():
        with op.batch_alter_table("study_session") as b:
            b.alter_column("mode", nullable=False)


def downgrade():
    with _fks_off():
        with op.batch_alter_table("study_session") as b:
            b.drop_column("mode")
