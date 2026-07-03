"""Branch.faq — clinic FAQ the voice agent answers on calls.

Additive only. Nullable JSONB list of {"q","a"}; NULL/empty keeps the agent's
old "confirm at the clinic" fallback.

Revision ID: a24clinicfaq2026
Revises: z23judgeattempts2026
Create Date: 2026-07-03
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

revision = "a24clinicfaq2026"
down_revision = "z23judgeattempts2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("faq", JSONB(), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "faq")
