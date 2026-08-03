"""Ledger for one-off charges that are not subscription cycles.

Found in production 2026-08-03: a clinic paid ₹1,499 for the WhatsApp add-on,
the feature switched on, and the payment appeared NOWHERE in the ops Payments
list — that list reads billing_cycles, and an add-on deliberately does not
create a cycle (doing so would start a billing period nobody bought and
corrupt minutes accounting). The money existed only in Razorpay and as a
boolean on the branch.

razorpay_payment_id is UNIQUE so a webhook redelivery cannot book the same
payment twice.

Additive and independent of existing tables, so it is safe to apply ahead of
the deploy.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "oo38_addon_purchases"
down_revision = "nn37_whatsapp_addon"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "addon_purchases",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id", UUID(as_uuid=True),
            sa.ForeignKey("organizations.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "branch_id", UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column("kind", sa.String(40), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("gst", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("razorpay_payment_id", sa.String(255), unique=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now()
        ),
    )
    op.create_index("ix_addon_purchases_org_id", "addon_purchases", ["org_id"])
    op.create_index("ix_addon_purchases_branch_id", "addon_purchases", ["branch_id"])


def downgrade() -> None:
    op.drop_index("ix_addon_purchases_branch_id", table_name="addon_purchases")
    op.drop_index("ix_addon_purchases_org_id", table_name="addon_purchases")
    op.drop_table("addon_purchases")
