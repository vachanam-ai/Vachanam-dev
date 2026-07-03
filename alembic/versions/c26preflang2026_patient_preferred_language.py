"""patients.preferred_language — per-caller spoken-language mapping.

Additive. Set when a caller explicitly asks the agent to switch languages
("can you speak English?"); all later calls to that phone start in it.

Revision ID: c26preflang2026
Revises: b25clinicq2026
Create Date: 2026-07-03
"""
import sqlalchemy as sa
from alembic import op

revision = "c26preflang2026"
down_revision = "b25clinicq2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("preferred_language", sa.String(8), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("patients", "preferred_language")
