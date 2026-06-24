"""Branch.welcome_short_audio — welcome-only clip for outbound calls.

Additive only. A nullable BYTEA holding the clinic's welcome-only WAV (no
inbound "how can I help" tail), played instantly on outbound reminder/rebook/
followup calls to mask session.start and say namaskaram exactly once.
NULL → live synth fallback.

Revision ID: x21welcomeshort2026
Revises: w20welcomeaudio2026
Create Date: 2026-06-24
"""
import sqlalchemy as sa
from alembic import op

revision = "x21welcomeshort2026"
down_revision = "w20welcomeaudio2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("welcome_short_audio", sa.LargeBinary(), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "welcome_short_audio")
