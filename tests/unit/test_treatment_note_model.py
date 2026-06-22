import uuid
from datetime import date
import pytest
from sqlalchemy import select
from backend.models.schema import TreatmentNote, Branch, Doctor, Patient, Organization


@pytest.mark.asyncio
async def test_treatment_note_persists_and_defaults(db):
    org = Organization(id=uuid.uuid4(), name="Clinic Test", owner_phone="+919000000000", owner_email="clinic@test.com", plan="clinic")
    db.add(org); await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="C", whatsapp_number="+919999999999", did_number="+910000000001")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000001")
    db.add_all([doc, pat]); await db.flush()
    note = TreatmentNote(
        branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
        visit_date=date(2026, 6, 22), steps_performed="cleaning",
        next_steps="floss", next_reporting_date=date(2026, 6, 25),
    )
    db.add(note); await db.flush()
    row = (await db.execute(select(TreatmentNote).where(TreatmentNote.id == note.id))).scalar_one()
    assert row.is_final is False
    assert row.branch_id == br.id and row.next_reporting_date == date(2026, 6, 25)
