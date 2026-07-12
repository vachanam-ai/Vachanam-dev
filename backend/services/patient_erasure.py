"""Shared patient-PII erasure (DPDP s.8(7) / right to erasure).

One implementation used by BOTH the automatic retention job
(backend/jobs/data_retention.py) and the clinic-initiated "end treatment &
delete data" action (backend/routers/treatment.py), so the two paths can
never drift on WHAT gets erased.

RULE 9: erases PII, logs IDs + last-4 only.
"""
from __future__ import annotations

from datetime import datetime, timezone

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import FollowupTask, Patient, TreatmentNote

logger = structlog.get_logger()

# Name is NOT NULL on patients — fixed placeholder rather than NULL.
ERASED_NAME = "[erased]"


async def erase_patient_pii(db: AsyncSession, p: Patient) -> None:
    """Erase one patient's PII in-place (caller commits).

    - name/phone/age/gender cleared, anonymized_at stamped (idempotent guard is
      the caller's job via anonymized_at IS NULL, but re-running is harmless).
    - Treatment notes DELETED (health data), follow-up thread health text NULLed
      (task rows survive for non-PII outcome trends).
    FK ORDER: FollowupTask.treatment_note_id -> treatment_notes is RESTRICT, so
    the link must be cleared BEFORE the notes are deleted.
    """
    now = datetime.now(timezone.utc)
    last4 = (p.phone or "")[-4:] or "----"
    p.name = ERASED_NAME
    p.phone = None
    p.age = None
    p.gender = None
    p.followup_consent = False
    p.anonymized_at = now

    await db.execute(
        FollowupTask.__table__.update()
        .where(FollowupTask.patient_id == p.id)
        .values(treatment_note_id=None, what_to_ask=None, response_summary=None)
    )
    await db.execute(
        TreatmentNote.__table__.delete().where(TreatmentNote.patient_id == p.id)
    )
    # An erased patient must never be dialed again — close any queued calls.
    await db.execute(
        FollowupTask.__table__.update()
        .where(FollowupTask.patient_id == p.id,
               FollowupTask.status.in_(("pending", "in_progress")))
        .values(status="completed")
    )

    logger.info(
        "patient_pii_erased",
        patient_id=str(p.id),
        branch_id=str(p.branch_id),
        phone_last4=last4,
    )
