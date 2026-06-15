"""branches.language — per-clinic voice-agent language selection.

Drives the Sarvam STT/TTS language codes and the per-language spoken lines +
system-prompt directive (agent/i18n). Default "te" (Telugu) — the launch market,
so every existing branch keeps its current behaviour.

Revision ID: l8lang2026
Revises: k7vobizcdr2026
Create Date: 2026-06-15
"""
import sqlalchemy as sa
from alembic import op

revision = "l8lang2026"
down_revision = "k7vobizcdr2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column("language", sa.String(8), nullable=False, server_default="te"),
    )


def downgrade() -> None:
    op.drop_column("branches", "language")
