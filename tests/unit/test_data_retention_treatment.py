"""Proof for Task 10 (M2): the DPDP retention/erasure job also wipes a patient's
treatment health-data when their PII is anonymised (RULE 9).

When a stale patient is anonymised:
  - their TreatmentNote rows (health-adjacent) are DELETED outright, and
  - the health text on their follow-up thread (FollowupTask.what_to_ask =
    doctor's question/advice, FollowupTask.response_summary = patient's reply)
    is NULLed — the task rows survive for non-PII outcome trends.

FK order: FollowupTask.treatment_note_id -> treatment_notes is RESTRICT, so the
job must NULL the FollowupTask link FIRST, then delete the treatment_notes.
"""
import uuid
from datetime import date, datetime, timezone, timedelta

import pytest
from sqlalchemy import select

from backend.models.schema import (
    Branch,
    Doctor,
    FollowupTask,
    Organization,
    Patient,
    TreatmentNote,
)
from backend.jobs.data_retention import run_data_retention
from backend.config import settings


@pytest.mark.asyncio
async def test_anonymise_wipes_treatment_notes_and_thread_text(db, monkeypatch):
    monkeypatch.setattr(settings, "patient_retention_days", 30, raising=False)
    old = datetime.now(timezone.utc) - timedelta(days=settings.patient_retention_days + 5)

    org = Organization(
        name="Ret Org", owner_phone="+919000000050",
        owner_email=f"ret-{uuid.uuid4().hex[:6]}@t.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        id=uuid.uuid4(), org_id=org.id, name="C",
        whatsapp_number=f"+9188{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(br)
    await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(
        id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000050",
        created_at=old,
    )
    db.add_all([doc, pat])
    await db.flush()
    n = TreatmentNote(
        branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
        visit_date=date(2026, 1, 1), steps_performed="root canal",
    )
    db.add(n)
    await db.flush()
    t = FollowupTask(
        branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
        task_type="doctor_advice", channel="voice",
        what_to_ask="advice", response_summary="still pain", treatment_note_id=n.id,
    )
    db.add(t)
    await db.commit()
    pid = pat.id

    await run_data_retention()
    db.expire_all()

    notes = (
        await db.execute(select(TreatmentNote).where(TreatmentNote.patient_id == pid))
    ).scalars().all()
    assert notes == []  # notes deleted on anonymise
    ft = (
        await db.execute(select(FollowupTask).where(FollowupTask.patient_id == pid))
    ).scalar_one()
    assert ft.what_to_ask is None and ft.response_summary is None  # health text wiped
