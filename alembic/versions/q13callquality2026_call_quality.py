"""call_quality table — per-call monitoring + feedback-loop capture.

One agent-written row per voice call: outcome metrics (non-PII, kept long-term)
plus an optional phone-masked transcript (PII, pruned after
transcript_retention_days by the data_retention job).

Revision ID: q13callquality2026
Revises: p12consent2026
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "q13callquality2026"
down_revision = "p12consent2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "call_quality",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "branch_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("branches.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column(
            "call_log_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("call_logs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("session_id", sa.String(255)),
        sa.Column("call_type", sa.String(20)),
        sa.Column("language", sa.String(8)),
        sa.Column("duration_seconds", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("turns", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("booking_made", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("booking_abandoned", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("transfer_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("fail_reason", sa.String(40), nullable=True),
        sa.Column("transcript", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_call_quality_branch_id", "call_quality", ["branch_id"])
    op.create_index("ix_call_quality_call_log_id", "call_quality", ["call_log_id"])
    op.create_index("ix_call_quality_created_at", "call_quality", ["created_at"])
    op.create_index(
        "ix_call_quality_branch_created", "call_quality", ["branch_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_call_quality_branch_created", table_name="call_quality")
    op.drop_index("ix_call_quality_created_at", table_name="call_quality")
    op.drop_index("ix_call_quality_call_log_id", table_name="call_quality")
    op.drop_index("ix_call_quality_branch_id", table_name="call_quality")
    op.drop_table("call_quality")
