"""FollowupTask thread link (treatment_note_id + created_by_user_id).

Sub-spec M2 (treatment progress + follow-up loop). Additive only — two
nullable FK columns plus an index on treatment_note_id, so follow-up calls
can form a thread linked to a treatment note.

- treatment_note_id: FK -> treatment_notes (RESTRICT), nullable, indexed.
- created_by_user_id: FK -> users (SET NULL), nullable.

task_type (existing app-side VARCHAR) additionally carries 'next_visit_book'
and 'doctor_advice' — no DB enum change.

Revision ID: s16followupthread2026
Revises: r15treatmentnotes2026
Create Date: 2026-06-22
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "s16followupthread2026"
down_revision = "r15treatmentnotes2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("followup_tasks", sa.Column("treatment_note_id", UUID(as_uuid=True),
        sa.ForeignKey("treatment_notes.id", ondelete="RESTRICT"), nullable=True))
    op.add_column("followup_tasks", sa.Column("created_by_user_id", UUID(as_uuid=True),
        sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True))
    op.create_index("ix_followup_tasks_treatment_note_id", "followup_tasks", ["treatment_note_id"])


def downgrade() -> None:
    op.drop_index("ix_followup_tasks_treatment_note_id", "followup_tasks")
    op.drop_column("followup_tasks", "created_by_user_id")
    op.drop_column("followup_tasks", "treatment_note_id")
