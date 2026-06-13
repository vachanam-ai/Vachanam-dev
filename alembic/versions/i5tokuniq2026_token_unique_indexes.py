"""Partial unique index on token-doctor queue numbers — race-proof Rule 2.

confirm_booking's capacity re-check (FIXLOG #48) closes the SEQUENTIAL
assign-skip double-book, but a re-count + INSERT is TOCTOU under concurrency
(bug-bounty T1). For TOKEN doctors the queue number is a day-wide sequence and
must be unique per (branch, doctor, date) — a partial unique index makes that
race-proof at the DB.

NOT added for SLOT doctors: their token_number is a PER-SLOT count (two
different times both start at 1), and a slot may legitimately hold
max_concurrent_per_slot > 1 — neither fits a simple unique index. The slot
skip-assign race is instead closed in the agent wrapper, which acquires the
atomic Redis hold (assign_token) before confirm when no hold exists.

confirm_booking catches the IntegrityError this raises and returns a clean
already_booked instead of a 500.

Revision ID: i5tokuniq2026
Revises: h4hardblock2026
Create Date: 2026-06-13
"""
from alembic import op

revision = "i5tokuniq2026"
down_revision = "h4hardblock2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_token_number_confirmed
        ON tokens (branch_id, doctor_id, date, token_number)
        WHERE status = 'confirmed' AND appointment_time IS NULL
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_token_number_confirmed")
