"""followup_tasks.target_date — the date the DOCTOR asked for on this reply

Vinay 2026-08-04: "if doctor sees the reply and advised to come next day
itself instead of the mentioned day, will it reschedule?"

It could not, because a doctor_advice call carried no date at all. The
follow-up job deliberately strips the note's date off advice calls (RULE 9: a
booking hint belonging to the note must not leak onto a doctor's message), so
there was nowhere for "come tomorrow instead" to live.

Its own column rather than reusing TreatmentNote.next_reporting_date: writing
back to the note would make "the doctor asked for this on THIS reply"
indistinguishable from "this note has always said that", and the job's leak
guard depends on telling those apart.

Revision ID: ss42_followup_target_date
Revises: rr41_doctor_session_events
"""
import sqlalchemy as sa
from alembic import op

revision = "ss42_followup_target_date"
down_revision = "rr41_doctor_session_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("followup_tasks", sa.Column("target_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("followup_tasks", "target_date")
