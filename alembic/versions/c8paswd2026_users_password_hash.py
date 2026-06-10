"""users.password_hash — email+password auth alongside Google Sign-In.

Revision ID: c8paswd2026
Revises: b7c1voice2026
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "c8paswd2026"
down_revision = "b7c1voice2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("users", sa.Column("password_hash", sa.String(255), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "password_hash")
