"""Razorpay recurring subscription state and immutable plan mapping.

Revision ID: vv45_razorpay_autopay
Revises: uu44_wa_delivery_outbox
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "vv45_razorpay_autopay"
down_revision = "uu44_wa_delivery_outbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "razorpay_subscription_status",
            sa.String(length=30),
            nullable=True,
        ),
    )
    op.create_table(
        "razorpay_plan_maps",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pricing_key", sa.String(length=120), nullable=False),
        sa.Column("plan", sa.String(length=20), nullable=False),
        sa.Column("amount_paise", sa.Integer(), nullable=False),
        sa.Column("razorpay_plan_id", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("pricing_key"),
        sa.UniqueConstraint("razorpay_plan_id"),
    )


def downgrade() -> None:
    op.drop_table("razorpay_plan_maps")
    op.drop_column("organizations", "razorpay_subscription_status")
