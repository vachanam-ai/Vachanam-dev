"""Add 'lite' to the plan_type enum (Vinay 2026-07-15: ₹1,999 entry plan for
low-volume clinics). Additive only — no existing rows change.

ALTER TYPE ... ADD VALUE cannot run inside a transaction block, so this
migration commits the surrounding transaction first and runs the ALTER with
autocommit (IF NOT EXISTS makes it idempotent/safe to re-run).
"""
from alembic import op

revision = "gg30_plan_lite"
down_revision = "ff29_whatsapp_ratings"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("COMMIT")
    op.execute("ALTER TYPE plan_type ADD VALUE IF NOT EXISTS 'lite'")


def downgrade() -> None:
    # Postgres cannot DROP a value from an enum. A rollback would require
    # recreating the type; not worth it for an additive value. No-op.
    pass
