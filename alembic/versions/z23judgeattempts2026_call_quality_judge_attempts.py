"""CallQuality.judge_attempts — retire permanently-failing judge rows (bounty B21).

Additive only — one NOT NULL integer column, server_default 0 so existing rows
are unchanged. The call-scoring job increments this on each failed judge attempt
and stamps judged_at (with a sentinel tag) once it hits MAX_JUDGE_ATTEMPTS, so a
malformed/rejected transcript stops being re-selected every run (head-of-line
blocking of all newer calls).

Revision ID: z23judgeattempts2026
Revises: y22patientdedup2026
Create Date: 2026-07-02
"""
import sqlalchemy as sa
from alembic import op

revision = "z23judgeattempts2026"
down_revision = "y22patientdedup2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_quality",
        sa.Column(
            "judge_attempts",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("call_quality", "judge_attempts")
