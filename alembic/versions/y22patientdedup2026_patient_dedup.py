"""Patient de-duplication: is_primary column, merge existing duplicates, and a
partial unique index on (branch_id, phone, lower(name)).

Additive + one-time data cleanup. Upgrade order: add column -> merge duplicate
patients (repoint tokens/treatment_notes/followup_tasks, delete dups) ->
backfill is_primary (one owner per phone; NULL-phone rows own primary) ->
create the partial unique index (safe now that duplicates are gone).

downgrade() drops the index + column only — the merge is NOT reversed
(irreversible data cleanup).

Revision ID: y22patientdedup2026
Revises: x21welcomeshort2026
Create Date: 2026-06-29
"""
import sqlalchemy as sa
from alembic import op

from backend.services.patient_dedup import MERGE_SQL, BACKFILL_PRIMARY_SQL

revision = "y22patientdedup2026"
down_revision = "x21welcomeshort2026"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "patients",
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    for stmt in MERGE_SQL:
        op.execute(stmt)
    for stmt in BACKFILL_PRIMARY_SQL:
        op.execute(stmt)
    op.create_index(
        "uq_patient_branch_phone_name",
        "patients",
        ["branch_id", "phone", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_patient_branch_phone_name", table_name="patients")
    op.drop_column("patients", "is_primary")
