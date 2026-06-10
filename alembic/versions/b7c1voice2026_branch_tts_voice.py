"""branches.tts_voice — per-clinic Sarvam TTS speaker selection.

Revision ID: b7c1voice2026
Revises: fd4a95d354fa
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "b7c1voice2026"
down_revision = "fd4a95d354fa"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "branches",
        sa.Column("tts_voice", sa.String(32), nullable=False, server_default="rupali"),
    )


def downgrade() -> None:
    op.drop_column("branches", "tts_voice")
