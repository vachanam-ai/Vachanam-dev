"""doctors.calendar_event_ids_recurring — one calendar event per session window

Vinay 2026-08-04: "doctors and their slots appear static from creation of
clinic."

The single `calendar_event_id_recurring` string can hold ONE event, so a doctor
sitting 9-12 and again 5-9 could not be represented; the router classed them
"complex", deleted their hours block, and the calendar kept showing whatever
was written at clinic setup.

The old column is deliberately left in place: it still points at the block
written under the previous scheme, and the new sync deletes that event only
after its replacements exist.

Revision ID: rr41_doctor_session_events
Revises: qq40_reminder_24h
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "rr41_doctor_session_events"
down_revision = "qq40_reminder_24h"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "doctors",
        sa.Column(
            "calendar_event_ids_recurring",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("doctors", "calendar_event_ids_recurring")
