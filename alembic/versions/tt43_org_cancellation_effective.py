"""organizations.cancellation_effective — scheduled end-of-cycle cancellation

Vinay 2026-08-07: "we need to add cancel option. where they can exit
completely. and effect will take place from coming month (after their current
cycle ends)."

Deliberately a DATE, not a boolean. A clinic that cancels has paid for the
cycle it is in, so it keeps full service until that cycle ends — the date IS
the promise. The same daily job that promotes pending_plan applies it.

Dropping voice but keeping WhatsApp is NOT a cancellation: that is a plan
change to `wa`, which the existing pending_plan mechanism already schedules for
the same moment.

Revision ID: tt43_org_cancellation
Revises: ss42_followup_target_date
"""
import sqlalchemy as sa
from alembic import op

revision = "tt43_org_cancellation"
down_revision = "ss42_followup_target_date"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column("cancellation_effective", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "cancellation_effective")
