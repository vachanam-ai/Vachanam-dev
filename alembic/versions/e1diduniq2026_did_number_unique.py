"""Partial-unique index on branches.did_number — no two clinics share a DID.

Partial (WHERE did_number IS NOT NULL) so multiple un-provisioned branches
with NULL DID remain valid.

Revision ID: e1diduniq2026
Revises: d9clinph2026
Create Date: 2026-06-11
"""
from alembic import op

revision = "e1diduniq2026"
down_revision = "d9clinph2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "uq_branches_did_number",
        "branches",
        ["did_number"],
        unique=True,
        postgresql_where="did_number IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index("uq_branches_did_number", table_name="branches")
