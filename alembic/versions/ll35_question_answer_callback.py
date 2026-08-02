"""clinic_questions — doctor answer + AI callback (Vinay 2026-08-02).

A question the receptionist/AI could not answer now goes to the doctor on the
dashboard: they open it, type the answer, and choose whether it joins the FAQ.
Either way Vachanam calls the patient back and speaks the answer — so the row
needs the caller's identity (patient link + full phone, the delivery address
for the promised callback, same justification as patient_messages) and its own
callback state machine.

status: pending (awaiting the doctor) -> answered (queued for callback)
        -> called (dispatch succeeded) | unreachable (no phone / attempts out)

Additive only; existing rows default to 'pending' with no phone, exactly the
FAQ-growth behaviour they had before.

Revision ID: ll35_question_answer
Revises: kk34_schema_alignment
Create Date: 2026-08-02
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "ll35_question_answer"
down_revision: str | Sequence[str] | None = "kk34_schema_alignment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "clinic_questions",
        sa.Column("patient_id", UUID(as_uuid=True), sa.ForeignKey("patients.id", ondelete="SET NULL"), nullable=True),
    )
    op.add_column("clinic_questions", sa.Column("caller_phone", sa.String(20), nullable=True))
    op.add_column("clinic_questions", sa.Column("answer", sa.String(1000), nullable=True))
    op.add_column("clinic_questions", sa.Column("answered_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("clinic_questions", sa.Column("added_to_faq", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column(
        "clinic_questions",
        sa.Column("status", sa.String(12), nullable=False, server_default="pending"),
    )
    op.add_column(
        "clinic_questions",
        sa.Column("call_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    # The callback dispatcher scans one branch-agnostic predicate every 5 min.
    op.create_index("ix_clinic_questions_status", "clinic_questions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_clinic_questions_status", table_name="clinic_questions")
    for col in (
        "call_attempts", "status", "added_to_faq", "answered_at",
        "answer", "caller_phone", "patient_id",
    ):
        op.drop_column("clinic_questions", col)
