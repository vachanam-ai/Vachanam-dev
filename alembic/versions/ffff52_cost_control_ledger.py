"""Cost-control usage ledger and provider snapshots.

Revision ID: ffff52_cost_control_ledger
Revises: eeee51_whatsapp_signup_v4
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "ffff52_cost_control_ledger"
down_revision = "eeee51_whatsapp_signup_v4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_quality",
        sa.Column("stt_audio_seconds", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "call_quality",
        sa.Column("tts_audio_seconds", sa.Float(), server_default="0", nullable=False),
    )
    op.add_column(
        "call_quality",
        sa.Column("llm_prompt_tokens", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "call_quality",
        sa.Column("llm_cached_tokens", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column(
        "call_quality",
        sa.Column("llm_completion_tokens", sa.BigInteger(), server_default="0", nullable=False),
    )
    op.add_column("call_quality", sa.Column("usage_rate_version", sa.String(32)))
    op.add_column(
        "call_quality", sa.Column("measured_ai_cost_inr", sa.Numeric(14, 6))
    )

    op.create_table(
        "infrastructure_usage_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider", sa.String(32), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("source", sa.String(64), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("used", sa.Numeric(20, 4)),
        sa.Column("limit", sa.Numeric(20, 4)),
        sa.Column("unit", sa.String(32)),
        sa.Column("cost_inr", sa.Numeric(14, 4)),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text())),
        sa.Column("error", sa.String(240)),
        sa.Column(
            "captured_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_infra_usage_provider_captured",
        "infrastructure_usage_snapshots",
        ["provider", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_infra_usage_provider_captured",
        table_name="infrastructure_usage_snapshots",
    )
    op.drop_table("infrastructure_usage_snapshots")
    op.drop_column("call_quality", "measured_ai_cost_inr")
    op.drop_column("call_quality", "usage_rate_version")
    op.drop_column("call_quality", "llm_completion_tokens")
    op.drop_column("call_quality", "llm_cached_tokens")
    op.drop_column("call_quality", "llm_prompt_tokens")
    op.drop_column("call_quality", "tts_audio_seconds")
    op.drop_column("call_quality", "stt_audio_seconds")
