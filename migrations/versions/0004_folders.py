"""Add folder table; deck gains folder_id + last_opened_at.

Folders are a lightweight grouping layer above decks. A deck's folder_id
is nullable (unfiled) and ON DELETE SET NULL — deleting a folder never
deletes its decks by itself; the "also delete decks" checkbox in the UI
walks contained decks individually through the existing single-deck
delete path instead, so cascades to cards/sessions/attempts follow the
normal rules.

last_opened_at tracks the most recent GET /decks/<id> view, for the
landing page's "Recently opened" section. Existing rows get NULL/NULL —
no backfill.

Revision ID: 0004_folders
Revises: 0003_invite_used_by_set_null
Create Date: 2026-09-26
"""
from alembic import op
import sqlalchemy as sa


revision = "0004_folders"
down_revision = "0003_invite_used_by_set_null"
branch_labels = None
depends_on = None


def _deck_table(with_folder):
    cols = [
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE", name="fk_deck_user_id_user"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    ]
    if with_folder:
        cols.append(sa.Column(
            "folder_id", sa.Integer(),
            sa.ForeignKey("folder.id", ondelete="SET NULL", name="fk_deck_folder_id_folder"),
            nullable=True,
        ))
        cols.append(sa.Column("last_opened_at", sa.DateTime(), nullable=True))
    return sa.Table("deck", sa.MetaData(), *cols)


def upgrade():
    op.create_table(
        "folder",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "user_id", sa.Integer(),
            sa.ForeignKey("user.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("user_id", "name", name="uq_folder_user_id_name"),
    )
    op.create_index("ix_folder_user_id", "folder", ["user_id"])

    with op.batch_alter_table(
        "deck",
        copy_from=_deck_table(with_folder=False),
        recreate="always",
    ) as b:
        b.add_column(sa.Column("folder_id", sa.Integer(), nullable=True))
        b.add_column(sa.Column("last_opened_at", sa.DateTime(), nullable=True))
        b.create_foreign_key(
            "fk_deck_folder_id_folder", "folder", ["folder_id"], ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_deck_folder_id", "deck", ["folder_id"])
    op.create_index("ix_deck_last_opened_at", "deck", ["last_opened_at"])


def downgrade():
    op.drop_index("ix_deck_last_opened_at", table_name="deck")
    op.drop_index("ix_deck_folder_id", table_name="deck")

    with op.batch_alter_table(
        "deck",
        copy_from=_deck_table(with_folder=True),
        recreate="always",
    ) as b:
        b.drop_constraint("fk_deck_folder_id_folder", type_="foreignkey")
        b.drop_column("last_opened_at")
        b.drop_column("folder_id")

    op.drop_index("ix_folder_user_id", table_name="folder")
    op.drop_table("folder")
