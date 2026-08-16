"""Add the one-time Founding 100 voice credit.

Revision ID: dddd50_founding_voice_credit
Revises: cccc49_notification_preferences
"""
from alembic import op
import sqlalchemy as sa


revision = "dddd50_founding_voice_credit"
down_revision = "cccc49_notification_preferences"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("founding_member", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "organizations",
        sa.Column("founding_credit_minutes", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("organizations", "founding_credit_minutes")
    op.drop_column("organizations", "founding_member")
