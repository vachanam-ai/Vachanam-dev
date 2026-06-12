"""organizations.hard_block_on_exhaust — super-admin kill switch.

When enabled and the org's voice minutes for the current month reach the
plan's included minutes, the voice agent answers with a one-line "service
unavailable" message and hangs up (never dead air — RULE 8). Off by default:
overage billing is the normal path; hard block is for non-payers.

Revision ID: h4hardblock2026
Revises: g3calllog2026
Create Date: 2026-06-12
"""
import sqlalchemy as sa
from alembic import op

revision = "h4hardblock2026"
down_revision = "g3calllog2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "hard_block_on_exhaust",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "hard_block_on_exhaust")
