"""Add branch notification channel preferences and 24h retry counter.

Revision ID: cccc49_notification_preferences
Revises: bbb48_merge_heads
"""
from alembic import op
import sqlalchemy as sa


revision = "cccc49_notification_preferences"
down_revision = "bbb48_merge_heads"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column("reminder_calls_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "branches",
        sa.Column("followup_calls_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
    )
    op.add_column(
        "tokens",
        sa.Column("reminder_24h_dial_attempts", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("tokens", "reminder_24h_dial_attempts")
    op.drop_column("branches", "followup_calls_enabled")
    op.drop_column("branches", "reminder_calls_enabled")
