"""Audit security constraints and session invalidation state.

Revision ID: ii32_audit_security
Revises: hh31_message_read_at
"""
import sqlalchemy as sa
from alembic import op

revision = "ii32_audit_security"
down_revision = "hh31_message_read_at"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "support_tickets",
        sa.Column("anonymous_session_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_support_tickets_anonymous_session_id",
        "support_tickets",
        ["anonymous_session_id"],
    )
    op.create_unique_constraint(
        "uq_billing_cycles_razorpay_payment_id",
        "billing_cycles",
        ["razorpay_payment_id"],
    )
    op.create_unique_constraint(
        "uq_branches_google_calendar_id",
        "branches",
        ["google_calendar_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_branches_google_calendar_id", "branches", type_="unique"
    )
    op.drop_constraint(
        "uq_billing_cycles_razorpay_payment_id", "billing_cycles", type_="unique"
    )
    op.drop_index(
        "ix_support_tickets_anonymous_session_id", table_name="support_tickets"
    )
    op.drop_column("support_tickets", "anonymous_session_id")
    op.drop_column("users", "token_version")
