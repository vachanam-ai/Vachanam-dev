"""patients.age + patients.gender — basic demographics for family bookings.

A caller often books for a family member, so caller != patient. The agent
asks the patient's name and age (gender when offered); phone defaults to the
caller's number. Both columns nullable — old records and walk-ins without
demographics stay valid.

Revision ID: f2patdemo2026
Revises: e1diduniq2026
Create Date: 2026-06-11
"""
import sqlalchemy as sa
from alembic import op

revision = "f2patdemo2026"
down_revision = "e1diduniq2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("patients", sa.Column("age", sa.Integer(), nullable=True))
    op.add_column("patients", sa.Column("gender", sa.String(10), nullable=True))


def downgrade() -> None:
    op.drop_column("patients", "gender")
    op.drop_column("patients", "age")
