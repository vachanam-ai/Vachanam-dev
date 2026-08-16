"""Convert unactivated Founding 100 members to the 14-day unlimited trial.

Revision ID: jjjj56_founding_unlimited_trial
Revises: iiii55_custom_voice_offer
"""
from alembic import op
import sqlalchemy as sa


revision = "jjjj56_founding_unlimited_trial"
down_revision = "iiii55_custom_voice_offer"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Paid clinics keep historical credits exactly as invoiced. Only founding
    # accounts that never activated a subscription move to the replacement
    # offer, so no customer loses something already purchased.
    op.execute(
        sa.text(
            """
            UPDATE organizations
            SET status = 'trial',
                trial_ends_at = NOW() + INTERVAL '14 days',
                founding_credit_minutes = 0
            WHERE founding_member IS TRUE
              AND status = 'paused'
              AND subscription_started_at IS NULL
              AND trial_ends_at IS NULL
            """
        )
    )


def downgrade() -> None:
    # A trial may have taken real calls after upgrade. Reversing customer
    # entitlement automatically would be destructive, so rollback is a no-op.
    pass
