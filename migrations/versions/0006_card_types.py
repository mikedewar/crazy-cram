"""Card types: written / multiple-choice / true-false.

Additive migration — existing cards and attempts are backfilled as
``card_type="written"``, which is the historical behaviour. Adds:

* ``card.card_type`` (non-null, default "written")
* ``card.mc_random`` (nullable; only meaningful for MC cards)
* ``card_distractor`` (fixed distractors for MC-fixed cards)
* ``study_attempt.card_type`` (non-null, backfilled "written")
* ``study_attempt.options_json`` (nullable; shown options for MC/TF)

Revision ID: 0006_card_types
Revises: 0005_deck_color
Create Date: 2026-10-18
"""
from alembic import op
import sqlalchemy as sa


revision = "0006_card_types"
down_revision = "0005_deck_color"
branch_labels = None
depends_on = None


def upgrade():
    # --- card: card_type + mc_random -----------------------------------
    # Add as nullable first, backfill, then enforce NOT NULL on card_type.
    with op.batch_alter_table("card") as b:
        b.add_column(sa.Column("card_type", sa.String(length=16), nullable=True))
        b.add_column(sa.Column("mc_random", sa.Boolean(), nullable=True))

    op.execute(sa.text("UPDATE card SET card_type = 'written' WHERE card_type IS NULL"))

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
    with op.batch_alter_table("study_attempt") as b:
        b.add_column(sa.Column("card_type", sa.String(length=16), nullable=True))
        b.add_column(sa.Column("options_json", sa.Text(), nullable=True))

    op.execute(sa.text("UPDATE study_attempt SET card_type = 'written' WHERE card_type IS NULL"))

    with op.batch_alter_table("study_attempt") as b:
        b.alter_column("card_type", nullable=False, existing_type=sa.String(length=16))


def downgrade():
    with op.batch_alter_table("study_attempt") as b:
        b.drop_column("options_json")
        b.drop_column("card_type")

    op.drop_table("card_distractor")

    with op.batch_alter_table("card") as b:
        b.drop_column("mc_random")
        b.drop_column("card_type")
