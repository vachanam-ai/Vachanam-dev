"""branches.tts_voice → smallest.ai voice_id (nullable, widened).

TTS provider switched Sarvam Bulbul → smallest.ai Waves (Vinay 2026-06-15).
tts_voice now holds a smallest voice_id (possibly a cloned voice). It becomes
nullable (NULL → the agent uses the language's default smallest voice) and is
widened to 64 chars for cloned-voice IDs. Existing rows holding the old Sarvam
default 'rupali' are reset to NULL so non-mr/bn/or clinics don't get a voice
that can't speak their language.

Revision ID: n10smallestvoice2026
Revises: m9subacct2026
Create Date: 2026-06-15
"""
import sqlalchemy as sa
from alembic import op

revision = "n10smallestvoice2026"
down_revision = "m9subacct2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "branches",
        "tts_voice",
        existing_type=sa.String(32),
        type_=sa.String(64),
        nullable=True,
        server_default=None,
    )
    # Old Sarvam speaker default — meaningless for smallest.ai; reset so the
    # per-language default voice applies.
    op.execute("UPDATE branches SET tts_voice = NULL WHERE tts_voice = 'rupali'")


def downgrade() -> None:
    op.execute("UPDATE branches SET tts_voice = 'rupali' WHERE tts_voice IS NULL")
    op.alter_column(
        "branches",
        "tts_voice",
        existing_type=sa.String(64),
        type_=sa.String(32),
        nullable=False,
        server_default="rupali",
    )
