"""LLM-as-judge columns on call_quality (feedback loop, step 3).

Derived non-PII quality read written by the call_scoring job: overall score,
issue tags, a one-line PII-free summary, and judged_at.

Revision ID: q14callscore2026
Revises: q13callquality2026
Create Date: 2026-06-17
"""
import sqlalchemy as sa
from alembic import op

revision = "q14callscore2026"
down_revision = "q13callquality2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("call_quality", sa.Column("judge_score", sa.Integer(), nullable=True))
    op.add_column("call_quality", sa.Column("judge_tags", sa.JSON(), nullable=True))
    op.add_column("call_quality", sa.Column("judge_summary", sa.Text(), nullable=True))
    op.add_column(
        "call_quality", sa.Column("judged_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Partial index for the job's hot query: unjudged rows that have a transcript.
    op.create_index(
        "ix_call_quality_unjudged",
        "call_quality",
        ["created_at"],
        postgresql_where=sa.text("judged_at IS NULL AND transcript IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_call_quality_unjudged", table_name="call_quality")
    op.drop_column("call_quality", "judged_at")
    op.drop_column("call_quality", "judge_summary")
    op.drop_column("call_quality", "judge_tags")
    op.drop_column("call_quality", "judge_score")
