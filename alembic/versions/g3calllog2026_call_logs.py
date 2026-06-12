"""call_logs — one row per voice call, for analytics + minute metering.

PII discipline (Rule 9): caller stored as LAST-4 only; no names, no audio.

Revision ID: g3calllog2026
Revises: f2patdemo2026
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "g3calllog2026"
down_revision = "f2patdemo2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_logs",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        ),
        sa.Column("call_type", sa.String(20), nullable=False),  # inbound|reminder|cascade_rebook|outbound
        sa.Column("caller_last4", sa.String(4), nullable=True),
        sa.Column("answered", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("booking_made", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.create_index("ix_call_logs_branch_started", "call_logs", ["branch_id", "started_at"])


def downgrade() -> None:
    op.drop_index("ix_call_logs_branch_started", table_name="call_logs")
    op.drop_table("call_logs")
