"""Card types: written / multiple-choice / true-false.

Additive migration - existing cards and attempts are backfilled as
``card_type="written"``, which is the historical behaviour. Adds:

* ``card.card_type`` (non-null, default "written")
* ``card.mc_random`` (nullable; only meaningful for MC cards)
* ``card_distractor`` (fixed distractors for MC-fixed cards)
* ``study_attempt.card_type`` (non-null, backfilled "written")
* ``study_attempt.options_json`` (nullable; shown options for MC/TF)

SQLite note: batch_alter_table rebuilds the table via copy-and-rename.
With PRAGMA foreign_keys=ON (as the app sets per-connection) the
study_attempt.card_id ON DELETE SET NULL cascade fires against the
dropped table and nulls every row. We disable FKs for the duration of
each batch_alter_table and restore them after.

Revision ID: 0006_card_types
Revises: 0005_deck_color
Create Date: 2026-10-18
"""
from contextlib import contextmanager

from alembic import op
import sqlalchemy as sa


revision = "0006_card_types"
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
    # --- card: card_type + mc_random -----------------------------------
    # Add as nullable first, backfill, then enforce NOT NULL on card_type.
    with _fks_off():
        with op.batch_alter_table("card") as b:
            b.add_column(sa.Column("card_type", sa.String(length=16), nullable=True))
            b.add_column(sa.Column("mc_random", sa.Boolean(), nullable=True))

    op.execute(sa.text("UPDATE card SET card_type = 'written' WHERE card_type IS NULL"))

    with _fks_off():
        with op.batch_alter_table("card") as b:
            b.alter_column("card_type", nullable=False, existing_type=sa.String(length=16))

    # --- card_distractor -----------------------------------------------
    op.create_table(
        "card_distractor",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "card_id", sa.Integer(),
            sa.ForeignKey("card.id", ondelete="CASCADE"),
            nullable=False, index=True,
        ),
        sa.Column("text", sa.String(length=500), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(),
            server_default=sa.func.current_timestamp(), nullable=False,
        ),
        sa.UniqueConstraint("card_id", "position", name="uq_card_distractor_card_pos"),
    )

    # --- study_attempt: card_type + options_json -----------------------
    with _fks_off():
        with op.batch_alter_table("study_attempt") as b:
            b.add_column(sa.Column("card_type", sa.String(length=16), nullable=True))
            b.add_column(sa.Column("options_json", sa.Text(), nullable=True))

    op.execute(sa.text("UPDATE study_attempt SET card_type = 'written' WHERE card_type IS NULL"))

    with _fks_off():
        with op.batch_alter_table("study_attempt") as b:
            b.alter_column("card_type", nullable=False, existing_type=sa.String(length=16))


def downgrade():
    with _fks_off():
        with op.batch_alter_table("study_attempt") as b:
            b.drop_column("options_json")
            b.drop_column("card_type")

    op.drop_table("card_distractor")

    with _fks_off():
        with op.batch_alter_table("card") as b:
            b.drop_column("mc_random")
            b.drop_column("card_type")
