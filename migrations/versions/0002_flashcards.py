"""Add deck, card, study_session, study_attempt tables.

Revision ID: 0002_flashcards
Revises: 0001_baseline_v0
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0002_flashcards"
down_revision = "0001_baseline_v0"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "deck",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_deck_user_id", "deck", ["user_id"])

    op.create_table(
        "card",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "deck_id", sa.Integer(),
            sa.ForeignKey("deck.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("question", sa.String(length=500), nullable=False),
        sa.Column("answer", sa.String(length=500), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_card_deck_id", "card", ["deck_id"])

    op.create_table(
        "study_session",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "deck_id", sa.Integer(),
            sa.ForeignKey("deck.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("n_cards", sa.Integer(), nullable=False),
        sa.Column("shuffled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("score", sa.Integer(), nullable=True),
    )
    op.create_index("ix_study_session_user_id", "study_session", ["user_id"])
    op.create_index("ix_study_session_deck_id", "study_session", ["deck_id"])

    op.create_table(
        "study_attempt",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "session_id", sa.Integer(),
            sa.ForeignKey("study_session.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "card_id", sa.Integer(),
            sa.ForeignKey("card.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("card_snapshot_q", sa.String(length=500), nullable=False),
        sa.Column("card_snapshot_a", sa.String(length=500), nullable=False),
        sa.Column("student_answer", sa.String(length=500), nullable=True),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("attempted_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_study_attempt_session_id", "study_attempt", ["session_id"])
    op.create_index("ix_study_attempt_card_id", "study_attempt", ["card_id"])


def downgrade():
    op.drop_index("ix_study_attempt_card_id", table_name="study_attempt")
    op.drop_index("ix_study_attempt_session_id", table_name="study_attempt")
    op.drop_table("study_attempt")

    op.drop_index("ix_study_session_deck_id", table_name="study_session")
    op.drop_index("ix_study_session_user_id", table_name="study_session")
    op.drop_table("study_session")

    op.drop_index("ix_card_deck_id", table_name="card")
    op.drop_table("card")

    op.drop_index("ix_deck_user_id", table_name="deck")
    op.drop_table("deck")
