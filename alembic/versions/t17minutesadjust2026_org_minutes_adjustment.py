"""Organization.minutes_adjustment — super-admin per-clinic minute override.

Additive only — one nullable-defaulted integer column. A signed delta the
super-admin can set to grant or claw back voice minutes for a single clinic on
top of its plan/trial bucket (effective_included = base + adjustment, floored
at 0). Default 0 → existing clinics unchanged.

Revision ID: t17minutesadjust2026
Revises: s16followupthread2026
Create Date: 2026-06-23
"""
import sqlalchemy as sa
from alembic import op

revision = "t17minutesadjust2026"
down_revision = "s16followupthread2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "organizations",
        sa.Column(
            "minutes_adjustment",
            sa.Integer(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("organizations", "minutes_adjustment")
