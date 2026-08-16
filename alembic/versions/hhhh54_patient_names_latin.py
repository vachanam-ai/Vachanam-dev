"""Normalize existing patient names to the Latin storage contract.

Revision ID: hhhh54_patient_names_latin
Revises: gggg53_voice_usage_payment
"""
import sqlalchemy as sa
from alembic import op

from backend.services.patient_dedup import MERGE_SQL
from backend.services.patient_identity import normalize_patient_name


revision = "hhhh54_patient_names_latin"
down_revision = "gggg53_voice_usage_payment"
branch_labels = None
depends_on = None


_CURRENT_PATIENT_REPOINT_SQL = [
    """
    WITH ranked AS (
        SELECT id,
               first_value(id) OVER (
                   PARTITION BY branch_id, phone, lower(name)
                   ORDER BY created_at ASC, id ASC
               ) AS canonical_id
        FROM patients
        WHERE phone IS NOT NULL
    )
    UPDATE clinic_questions cq SET patient_id = ranked.canonical_id
    FROM ranked
    WHERE cq.patient_id = ranked.id AND ranked.id <> ranked.canonical_id;
    """,
    """
    WITH ranked AS (
        SELECT id,
               first_value(id) OVER (
                   PARTITION BY branch_id, phone, lower(name)
                   ORDER BY created_at ASC, id ASC
               ) AS canonical_id
        FROM patients
        WHERE phone IS NOT NULL
    )
    UPDATE patient_messages pm SET patient_id = ranked.canonical_id
    FROM ranked
    WHERE pm.patient_id = ranked.id AND ranked.id <> ranked.canonical_id;
    """,
    """
    WITH ranked AS (
        SELECT id,
               first_value(id) OVER (
                   PARTITION BY branch_id, phone, lower(name)
                   ORDER BY created_at ASC, id ASC
               ) AS canonical_id
        FROM patients
        WHERE phone IS NOT NULL
    )
    UPDATE ratings rt SET patient_id = ranked.canonical_id
    FROM ranked
    WHERE rt.patient_id = ranked.id AND ranked.id <> ranked.canonical_id;
    """,
    """
    WITH ranked AS (
        SELECT id,
               first_value(id) OVER (
                   PARTITION BY branch_id, phone, lower(name)
                   ORDER BY created_at ASC, id ASC
               ) AS canonical_id
        FROM patients
        WHERE phone IS NOT NULL
    )
    UPDATE patients canonical SET is_primary = TRUE
    FROM ranked, patients source
    WHERE canonical.id = ranked.canonical_id
      AND source.id = ranked.id
      AND ranked.id <> ranked.canonical_id
      AND source.is_primary = TRUE;
    """,
]


def upgrade() -> None:
    bind = op.get_bind()
    # Transliteration can collapse two historical spellings on the same phone
    # to one Latin name (for example, native-script "Vinay" plus an existing
    # Latin "Vinay"). Remove the guard while normalizing, then use the existing
    # audited patient merge to preserve every child record before restoring it.
    op.drop_index("uq_patient_branch_phone_name", table_name="patients")
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
    # The last historical merge statement deletes duplicate patients. Repoint
    # the three child tables introduced after that historical migration before
    # executing the delete, otherwise their SET NULL constraints lose identity.
    for statement in MERGE_SQL[:-1]:
        bind.execute(sa.text(statement))
    for statement in _CURRENT_PATIENT_REPOINT_SQL:
        bind.execute(sa.text(statement))
    bind.execute(sa.text(MERGE_SQL[-1]))
    op.create_index(
        "uq_patient_branch_phone_name",
        "patients",
        ["branch_id", "phone", sa.text("lower(name)")],
        unique=True,
        postgresql_where=sa.text("phone IS NOT NULL"),
    )


def downgrade() -> None:
    # Transliteration is intentionally irreversible; restoring mixed-script
    # patient identity would recreate the production bug this migration fixes.
    pass
