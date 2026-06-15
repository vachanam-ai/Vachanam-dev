"""branches.cloned_voices — per-clinic registered smallest.ai cloned voices.

A clinic clones a voice in the smallest.ai dashboard and registers the returned
voice_id here ([{voice_id, name, language}]) so it appears in the Settings voice
picker for that language and can be selected as the agent's voice. Tenant-scoped.

Revision ID: o11clonedvoices2026
Revises: n10smallestvoice2026
Create Date: 2026-06-16
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "o11clonedvoices2026"
down_revision = "n10smallestvoice2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column(
            "cloned_voices",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
    )


def downgrade() -> None:
    op.drop_column("branches", "cloned_voices")
