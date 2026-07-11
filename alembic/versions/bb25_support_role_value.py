"""add 'support' value to user_role enum (platform support staff)

Revision ID: bb25_support_role
Revises: aa24_support_tables
Create Date: 2026-07-11

Additive enum value only. Needed before any user row can have role='support'
(Phase 2 support-staff provisioning). Tests already carry the value via
create_all; this migration brings prod's real enum type in line.
"""
from alembic import op

revision = "bb25_support_role"
down_revision = "aa24_support_tables"
branch_labels = None
depends_on = None


def upgrade():
    # PG 12+ allows ADD VALUE inside a transaction; we never USE the value in
    # this same migration, so it's safe. IF NOT EXISTS keeps it idempotent.
    op.execute("ALTER TYPE user_role ADD VALUE IF NOT EXISTS 'support'")


def downgrade():
    # Postgres cannot DROP a single enum value. Leaving it is harmless — no row
    # uses it after a rollback of Phase 2. (Full removal would require recreating
    # the type, which is out of scope for a down-migration.)
    pass
