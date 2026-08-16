"""Normalize existing patient names to the Latin storage contract.

Revision ID: hhhh54_patient_names_latin
Revises: gggg53_voice_usage_payment
"""
import sqlalchemy as sa
from alembic import op

from backend.services.patient_identity import normalize_patient_name


revision = "hhhh54_patient_names_latin"
down_revision = "gggg53_voice_usage_payment"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    patients = sa.table(
        "patients",
        sa.column("id", sa.Uuid()),
        sa.column("name", sa.String()),
    )
    rows = bind.execute(sa.select(patients.c.id, patients.c.name)).all()
    for patient_id, name in rows:
        if not name or not any(ch.isalpha() and not ch.isascii() for ch in name):
            continue
        try:
            normalized = normalize_patient_name(name)
        except ValueError:
            # Unsupported historical scripts stay visible for manual cleanup;
            # a migration must never make an existing patient unreachable.
            continue
        bind.execute(
            sa.update(patients)
            .where(patients.c.id == patient_id)
            .values(name=normalized)
        )


def downgrade() -> None:
    # Transliteration is intentionally irreversible; restoring mixed-script
    # patient identity would recreate the production bug this migration fixes.
    pass
