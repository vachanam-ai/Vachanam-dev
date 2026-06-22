"""Task 6: idempotent next-visit follow-up enqueue/cancel service.

Seed notes (vs brief):
  - Branch.org_id is a RESTRICT FK to organizations.id → seed an Organization row
    first (brief used a bare uuid4, which trips the FK).
  - Branch.whatsapp_number is NOT NULL + unique → seeded (brief used only
    did_number, which is nullable; whatsapp_number is the required column).
  - Doctor.booking_type is NOT NULL with no default → seeded ("token").
"""
import uuid
from datetime import date

import pytest
from sqlalchemy import select

from backend.models.schema import (
    Branch, Doctor, Patient, Organization, TreatmentNote, FollowupTask,
)
from backend.services.treatment_followup import sync_note_followup


async def _seed(db):
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone="+919000099030",
                        owner_email=f"owner-{org_id}@c.com", plan="clinic"))
    await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C",
                did_number=f"+9100{uuid.uuid4().hex[:9]}",
                whatsapp_number=f"+9100{uuid.uuid4().hex[:9]}")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000030")
    db.add_all([doc, pat]); await db.flush()
    return br, doc, pat


def _note(br, doc, pat, **kw):
    return TreatmentNote(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                         visit_date=date(2026, 6, 22), **kw)


@pytest.mark.asyncio
async def test_enqueue_creates_next_visit_book(db):
    br, doc, pat = await _seed(db)
    n = _note(br, doc, pat, next_reporting_date=date(2026, 6, 25)); db.add(n); await db.flush()
    await sync_note_followup(n, followup_question="how is the pain?", created_by=None, db=db)
    tasks = (await db.execute(select(FollowupTask).where(FollowupTask.patient_id == pat.id))).scalars().all()
    assert len(tasks) == 1
    assert tasks[0].task_type == "next_visit_book"
    assert tasks[0].scheduled_date == date(2026, 6, 23)   # visit_date + 1
    assert tasks[0].what_to_ask == "how is the pain?"
    assert tasks[0].status == "pending" and tasks[0].channel == "voice"


@pytest.mark.asyncio
async def test_newer_note_cancels_prior_pending(db):
    br, doc, pat = await _seed(db)
    n1 = _note(br, doc, pat, next_reporting_date=date(2026, 6, 25)); db.add(n1); await db.flush()
    await sync_note_followup(n1, followup_question=None, created_by=None, db=db)
    n2 = _note(br, doc, pat, next_reporting_date=date(2026, 6, 28)); db.add(n2); await db.flush()
    await sync_note_followup(n2, followup_question=None, created_by=None, db=db)
    pend = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat.id, FollowupTask.status == "pending"))).scalars().all()
    assert len(pend) == 1   # only the latest survives
    # superseded prior task is DELETED, not lingering as "completed":
    all_tasks = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat.id,
        FollowupTask.task_type == "next_visit_book"))).scalars().all()
    assert len(all_tasks) == 1   # exactly one row total — no phantom row left behind
    completed = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat.id, FollowupTask.task_type == "next_visit_book",
        FollowupTask.status == "completed"))).scalars().all()
    assert completed == []   # no phantom completed follow-up


@pytest.mark.asyncio
async def test_final_note_cancels_and_does_not_enqueue(db):
    br, doc, pat = await _seed(db)
    n1 = _note(br, doc, pat, next_reporting_date=date(2026, 6, 25)); db.add(n1); await db.flush()
    await sync_note_followup(n1, followup_question=None, created_by=None, db=db)
    nf = _note(br, doc, pat, is_final=True); db.add(nf); await db.flush()
    await sync_note_followup(nf, followup_question=None, created_by=None, db=db)
    pend = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat.id, FollowupTask.status == "pending"))).scalars().all()
    assert pend == []
    # final note deletes the superseded pending task and enqueues nothing →
    # zero next_visit_book tasks remain, and none as a phantom "completed":
    all_tasks = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat.id,
        FollowupTask.task_type == "next_visit_book"))).scalars().all()
    assert len(all_tasks) == 0   # exactly zero rows total
    completed = (await db.execute(select(FollowupTask).where(
        FollowupTask.patient_id == pat.id, FollowupTask.task_type == "next_visit_book",
        FollowupTask.status == "completed"))).scalars().all()
    assert completed == []   # no phantom completed follow-up
