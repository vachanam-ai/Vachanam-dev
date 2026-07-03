"""clinic_questions — caller questions the FAQ couldn't answer.

Additive. The voice agent logs unanswered clinic-info questions so the owner
can discuss with the doctor and grow the FAQ (RULE 9: question + last-4 only).

Revision ID: b25clinicq2026
Revises: a24clinicfaq2026
Create Date: 2026-07-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "b25clinicq2026"
down_revision = "a24clinicfaq2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clinic_questions",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("branch_id", UUID(as_uuid=True),
                  sa.ForeignKey("branches.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.String(300), nullable=False),
        sa.Column("caller_last4", sa.String(4), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_clinic_questions_branch_id", "clinic_questions", ["branch_id"])


def downgrade() -> None:
    op.drop_table("clinic_questions")
