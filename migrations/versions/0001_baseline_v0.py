"""Baseline: v0 schema (user + invite_code).

Revision ID: 0001_baseline_v0
Revises:
Create Date: 2026-09-25
"""
from alembic import op
import sqlalchemy as sa


revision = "0001_baseline_v0"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "user",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("username", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("username", name="uq_user_username"),
    )
    op.create_index("ix_user_username", "user", ["username"])

    op.create_table(
        "invite_code",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("used_by", sa.Integer(), sa.ForeignKey("user.id"), nullable=True),
        sa.UniqueConstraint("code", name="uq_invite_code_code"),
    )
    op.create_index("ix_invite_code_code", "invite_code", ["code"])


def downgrade():
    op.drop_index("ix_invite_code_code", table_name="invite_code")
    op.drop_table("invite_code")
    op.drop_index("ix_user_username", table_name="user")
    op.drop_table("user")
