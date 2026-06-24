"""Branch.name_spoken — clinic name transliterated into the call's TTS script.

Additive only. A nullable column holding the clinic name in the spoken script
(e.g. "దత్త" for "Datta") so TTS speaks it instead of reading the Latin form as
English ("data"). Transliterated + stored lazily by the agent; NULL = use `name`.

Revision ID: v19clinicspoken2026
Revises: u18pendingplan2026
Create Date: 2026-06-24
"""
import sqlalchemy as sa
from alembic import op

revision = "v19clinicspoken2026"
down_revision = "u18pendingplan2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("name_spoken", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "name_spoken")
