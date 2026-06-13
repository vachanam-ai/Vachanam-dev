"""Add 'cancelled_by_patient' to the token_status enum (TD-020).

Patient-initiated cancels (voice agent _do_cancel) were stored as
'cancelled_by_clinic' — the only cancel value — conflating them with clinic
cascade-cancels (doctor leave) in analytics and risking a self-cancelled patient
getting a rebook call. A distinct value separates the two; rebook context filters
on cancelled_by_clinic only, so patient self-cancels are auto-excluded.

Postgres 12+ allows ALTER TYPE ... ADD VALUE inside a transaction. IF NOT EXISTS
makes it idempotent. Enum values cannot be dropped in Postgres, so downgrade is a
documented no-op.

Revision ID: j6cancelpatient2026
Revises: i5tokuniq2026
Create Date: 2026-06-13
"""
from alembic import op

revision = "j6cancelpatient2026"
down_revision = "i5tokuniq2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE token_status ADD VALUE IF NOT EXISTS 'cancelled_by_patient'")


def downgrade() -> None:
    # Postgres cannot DROP a value from an enum without recreating the type and
    # rewriting every dependent column. Intentional no-op — the extra value is
    # harmless if unused.
    pass
