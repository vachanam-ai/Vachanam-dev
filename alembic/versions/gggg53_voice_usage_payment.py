"""Record the separate Razorpay payment for a cycle's metered voice usage.

Revision ID: gggg53_voice_usage_payment
Revises: ffff52_cost_control_ledger
"""
import sqlalchemy as sa
from alembic import op


revision = "gggg53_voice_usage_payment"
down_revision = "ffff52_cost_control_ledger"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "billing_cycles",
        sa.Column("overage_order_id", sa.String(length=255), nullable=True),
    )
    op.add_column(
        "billing_cycles",
        sa.Column("overage_order_amount_paise", sa.Integer(), nullable=True),
    )
    op.add_column(
        "billing_cycles",
        sa.Column("overage_payment_id", sa.String(length=255), nullable=True),
    )
    op.create_unique_constraint(
        "uq_billing_cycles_overage_order_id",
        "billing_cycles",
        ["overage_order_id"],
    )
    op.create_unique_constraint(
        "uq_billing_cycles_overage_payment_id",
        "billing_cycles",
        ["overage_payment_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_billing_cycles_overage_payment_id",
        "billing_cycles",
        type_="unique",
    )
    op.drop_column("billing_cycles", "overage_payment_id")
    op.drop_constraint(
        "uq_billing_cycles_overage_order_id",
        "billing_cycles",
        type_="unique",
    )
    op.drop_column("billing_cycles", "overage_order_amount_paise")
    op.drop_column("billing_cycles", "overage_order_id")
