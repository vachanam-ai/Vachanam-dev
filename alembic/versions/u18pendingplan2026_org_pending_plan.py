"""Organization.pending_plan + pending_plan_effective — scheduled plan change.

Additive only. A clinic can switch plans any time; the change takes effect at
the next billing cycle (1st of next month), never mid-month, so it can't shrink
the minute bucket a clinic already paid for. A daily job applies the pending
plan once its effective date arrives. Both nullable → existing clinics
unchanged (no pending change).

Revision ID: u18pendingplan2026
Revises: t17minutesadjust2026
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = "u18pendingplan2026"
down_revision = "t17minutesadjust2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("pending_plan", sa.String(20), nullable=True))
    op.add_column(
        "organizations",
        sa.Column("pending_plan_effective", sa.Date(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("organizations", "pending_plan_effective")
    op.drop_column("organizations", "pending_plan")
