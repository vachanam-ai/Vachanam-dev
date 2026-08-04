"""tokens.reminder_24h_sent — a second, day-before reminder

Vinay 2026-08-04: "for appointments schedule a call 24hrs before if booked days
before. and 30mins before as is."

`reminder_sent` is a single boolean and cannot express "the day-before call
went, the half-hour one has not". Two reminders need two flags, or the first
suppresses the second.

Backfilled False: existing bookings simply become eligible, and the job's own
window (and its "only if booked ≥24h ahead" rule) keeps that from producing a
burst of calls about appointments that are already imminent.

Revision ID: qq40_reminder_24h
Revises: pp39_clinic_question_channel
"""
import sqlalchemy as sa
from alembic import op

revision = "qq40_reminder_24h"
down_revision = "pp39_clinic_question_channel"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tokens",
        sa.Column(
            "reminder_24h_sent", sa.Boolean(),
            nullable=False, server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("tokens", "reminder_24h_sent")
