"""Add section column to StudyAttempt for Learn mode.

Values: NULL for non-Learn runs (written, mc, flashcard), 1..5 for Learn.
We don't backfill — existing attempts stay NULL.

Revision ID: 0007_learn_section
Revises: 0006_study_mode
Create Date: 2026-10-19
"""
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0007_learn_section"
down_revision = "0006_study_mode"
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
        with op.batch_alter_table("study_attempt") as b:
            b.add_column(sa.Column("section", sa.Integer(), nullable=True))
    # Learn also needs to know which section is active on the session,
    # because an empty composed section has no attempts to key off.
    with _fks_off():
        with op.batch_alter_table("study_session") as b:
            b.add_column(sa.Column("learn_section", sa.Integer(), nullable=True))


def downgrade():
    with _fks_off():
        with op.batch_alter_table("study_session") as b:
            b.drop_column("learn_section")
    with _fks_off():
        with op.batch_alter_table("study_attempt") as b:
            b.drop_column("section")
