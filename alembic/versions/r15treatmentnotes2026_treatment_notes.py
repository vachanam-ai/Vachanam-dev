"""treatment_notes table (treatment progress notes).

Tracks treatment delivered and next actions per patient visit. Includes
visit_date, steps_performed, next_steps, next_reporting_date, is_final,
created_by_user_id, and timestamps. Back-links to Token (optional).
Multi-tenant scoped (branch_id) with indexes for tenant + patient + date queries.

Revision ID: r15treatmentnotes2026
Revises: q14callscore2026
Create Date: 2026-06-22
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "r15treatmentnotes2026"
down_revision = "q14callscore2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "treatment_notes",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("branch_id", UUID(as_uuid=True), sa.ForeignKey("branches.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("doctor_id", UUID(as_uuid=True), sa.ForeignKey("doctors.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("token_id", UUID(as_uuid=True), sa.ForeignKey("tokens.id", ondelete="RESTRICT"), nullable=True),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("steps_performed", sa.Text(), nullable=True),
        sa.Column("next_steps", sa.Text(), nullable=True),
        sa.Column("next_reporting_date", sa.Date(), nullable=True),
        sa.Column("is_final", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_by_user_id", UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_treatment_notes_branch_id", "treatment_notes", ["branch_id"])
    op.create_index("ix_treatment_notes_doctor_id", "treatment_notes", ["doctor_id"])
    op.create_index("ix_treatment_notes_patient_id", "treatment_notes", ["patient_id"])
    op.create_index("ix_treatment_notes_token_id", "treatment_notes", ["token_id"])
    op.create_index("ix_treatment_notes_branch_patient_date", "treatment_notes", ["branch_id", "patient_id", "visit_date"])
    op.create_index("ix_treatment_notes_branch_doctor", "treatment_notes", ["branch_id", "doctor_id"])


def downgrade() -> None:
    op.drop_table("treatment_notes")
