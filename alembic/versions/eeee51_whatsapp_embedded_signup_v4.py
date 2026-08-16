"""WhatsApp Embedded Signup v4 lifecycle state.

Revision ID: eeee51_whatsapp_signup_v4
Revises: dddd50_founding_voice_credit
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "eeee51_whatsapp_signup_v4"
down_revision = "dddd50_founding_voice_credit"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column("wa_onboarding", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("branches", "wa_onboarding")
