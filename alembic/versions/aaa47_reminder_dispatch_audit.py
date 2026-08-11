"""Add durable reminder dispatch audit fields.

Revision ID: aaa47_reminder_dispatch_audit
Revises: z23judgeattempts2026
"""
from alembic import op
import sqlalchemy as sa


revision = "aaa47_reminder_dispatch_audit"
down_revision = "z23judgeattempts2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tokens", sa.Column("reminder_30m_dispatched_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tokens", sa.Column("reminder_30m_dial_attempts", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("tokens", sa.Column("reminder_24h_dispatched_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("tokens", "reminder_24h_dispatched_at")
    op.drop_column("tokens", "reminder_30m_dial_attempts")
    op.drop_column("tokens", "reminder_30m_dispatched_at")
