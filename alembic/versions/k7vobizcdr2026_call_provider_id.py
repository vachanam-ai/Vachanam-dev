"""Add call_logs.provider_call_id for Vobiz CDR idempotent sync.

The Vobiz CDR sync job is the authoritative source of call minutes + counts
(agent-independent: survives dropped calls, crashes, local runs). provider_call_id
holds the telephony provider's call UUID; UNIQUE makes the upsert idempotent
across repeated syncs. NULL for agent-written rows.

Revision ID: k7vobizcdr2026
Revises: j6cancelpatient2026
Create Date: 2026-06-13
"""
import sqlalchemy as sa
from alembic import op

revision = "k7vobizcdr2026"
down_revision = "j6cancelpatient2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "call_logs",
        sa.Column("provider_call_id", sa.String(length=128), nullable=True),
    )
    op.create_unique_constraint(
        "uq_call_logs_provider_call_id", "call_logs", ["provider_call_id"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_call_logs_provider_call_id", "call_logs", type_="unique")
    op.drop_column("call_logs", "provider_call_id")
