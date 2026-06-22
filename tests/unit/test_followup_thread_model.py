import uuid
from datetime import date
import pytest
from sqlalchemy import select
from backend.models.schema import FollowupTask, Branch, Doctor, Patient, TreatmentNote, Organization


@pytest.mark.asyncio
async def test_followup_task_links_to_note(db):
    org = Organization(id=uuid.uuid4(), name="Clinic T5", owner_phone="+919000000020",
                       owner_email="clinic-t5@test.com", plan="clinic")
    db.add(org); await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="C",
                whatsapp_number="+919999000020", did_number="+910000000020")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000020")
    db.add_all([doc, pat]); await db.flush()
    note = TreatmentNote(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id, visit_date=date(2026,6,22))
    db.add(note); await db.flush()
    t = FollowupTask(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                     treatment_note_id=note.id, task_type="next_visit_book",
                     channel="voice", what_to_ask="how is your pain?",
                     scheduled_date=date(2026,6,23))
    db.add(t); await db.flush()
    row = (await db.execute(select(FollowupTask).where(FollowupTask.id == t.id))).scalar_one()
    assert row.treatment_note_id == note.id and row.task_type == "next_visit_book"
