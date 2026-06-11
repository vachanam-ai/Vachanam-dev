"""branches.clinic_phone — the clinic's existing patient-facing number.

Used for call-forwarding setup instructions (patients keep dialing it;
it forwards to the Vachanam DID).

Revision ID: d9clinph2026
Revises: c8paswd2026
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "d9clinph2026"
down_revision = "c8paswd2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("branches", sa.Column("clinic_phone", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("branches", "clinic_phone")
