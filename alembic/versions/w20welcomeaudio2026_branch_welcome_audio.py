"""Branch.welcome_audio — pre-rendered welcome+greeting WAV played on answer.

Additive only. A nullable BYTEA holding the clinic's welcome+greeting audio,
generated once (smallest.ai) and played INSTANTLY on call answer to mask the
~6s LiveKit session.start (Sarvam STT cold connect). NULL → live synth fallback.

Revision ID: w20welcomeaudio2026
Revises: v19clinicspoken2026
Create Date: 2026-06-24
"""
import sqlalchemy as sa
from alembic import op

revision = "w20welcomeaudio2026"
down_revision = "v19clinicspoken2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("welcome_audio", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "welcome_audio")
