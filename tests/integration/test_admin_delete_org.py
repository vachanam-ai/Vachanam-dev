"""Super-admin hard-delete of a clinic: FK-safe cascade across tenant tables.

Every tenant FK is ondelete=RESTRICT, so _hard_delete_org must remove children
in the right order or Postgres raises a FK violation. This seeds the trickiest
chain (token → treatment_note → followup_task, plus billing + user) and proves a
clean delete leaves nothing behind.
"""
import uuid
from datetime import date, time

import pytest
from sqlalchemy import func, select

from backend.models.schema import (
    BillingCycle,
    Branch,
    Doctor,
    FollowupTask,
    Organization,
    Patient,
    Token,
    TreatmentNote,
    User,
)

pytestmark = pytest.mark.asyncio


async def _seed_full_clinic(db):
    org = Organization(
        name="Fake Clinic", owner_phone="+919999900000",
        owner_email=f"del-{uuid.uuid4().hex[:8]}@realclinic.in",
        plan="solo", status="cancelled",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="Fake Branch",
        whatsapp_number=f"+9111{uuid.uuid4().hex[:9]}", status="active",
    )
    db.add(branch)
    await db.flush()
    doc = Doctor(
        branch_id=branch.id, name="Dr Test", specialization="dentistry",
        routing_keywords=["tooth"], booking_type="token",
        working_hours_start=time(9, 0), working_hours_end=time(17, 0),
        slot_duration_minutes=30, status="active",
    )
    pat = Patient(branch_id=branch.id, name="Pat", phone="+919666000011")
    db.add_all([doc, pat])
    await db.flush()
    tok = Token(
        branch_id=branch.id, doctor_id=doc.id, patient_id=pat.id,
        date=date.today(), token_number=1, appointment_time=time(10, 0),
        source="voice", status="confirmed",
    )
    db.add(tok)
    await db.flush()
    note = TreatmentNote(
        branch_id=branch.id, doctor_id=doc.id, patient_id=pat.id,
        token_id=tok.id, visit_date=date.today(), steps_performed="x",
    )
    db.add(note)
    await db.flush()
    db.add(FollowupTask(
        branch_id=branch.id, doctor_id=doc.id, patient_id=pat.id,
        token_id=tok.id, treatment_note_id=note.id, task_type="next_visit_book",
        channel="voice", status="pending",
    ))
    db.add(BillingCycle(
        org_id=org.id, cycle_start=date.today(), cycle_end=date.today(),
        plan="solo", base_amount=1999, included_minutes=100,
    ))
    db.add(User(
        org_id=org.id, email=f"u-{uuid.uuid4().hex[:8]}@realclinic.in",
        role="org_admin", branch_ids=[str(branch.id)],
    ))
    await db.commit()
    return org, branch


async def test_hard_delete_removes_all_tenant_data(db):
    from backend.routers.admin import _hard_delete_org

    org, branch = await _seed_full_clinic(db)
    org_id, branch_id = org.id, branch.id

    await _hard_delete_org(db, org)
    await db.commit()

    async def _count(model, col, val):
        return (await db.execute(select(func.count()).where(col == val))).scalar_one()

    assert await _count(Organization, Organization.id, org_id) == 0
    assert await _count(Branch, Branch.org_id, org_id) == 0
    assert await _count(Doctor, Doctor.branch_id, branch_id) == 0
    assert await _count(Patient, Patient.branch_id, branch_id) == 0
    assert await _count(Token, Token.branch_id, branch_id) == 0
    assert await _count(TreatmentNote, TreatmentNote.branch_id, branch_id) == 0
    assert await _count(FollowupTask, FollowupTask.branch_id, branch_id) == 0
    assert await _count(BillingCycle, BillingCycle.org_id, org_id) == 0
    assert await _count(User, User.org_id, org_id) == 0
