"""End-treatment endpoint (one-time visitor cleanup + DPDP erase option).

  - end without erase: notes for the thread deleted, pending follow-ups
    completed, patient PII untouched
  - end with erase_data: PII wiped via the shared erasure path
  - cross-branch denied (RULE 1)
"""
import uuid
from datetime import date

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from backend.main import app
from backend.middleware.auth_middleware import CurrentUser, get_current_user
from backend.models.schema import (
    Branch, Doctor, FollowupTask, Organization, Patient, TreatmentNote, User,
)

pytestmark = pytest.mark.asyncio


def _as_user(branch_id, org_id, user_id):
    return CurrentUser(user_id=str(user_id), email="d@c.com", role="org_admin",
                       org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
                       jti=str(uuid.uuid4()))


async def _seed(db, phone_suffix):
    org_id = uuid.uuid4()
    db.add(Organization(id=org_id, name="Org", owner_phone=f"+91900009{phone_suffix}",
                        owner_email=f"o-{org_id}@c.com", plan="clinic"))
    await db.flush()
    usr = User(id=uuid.uuid4(), org_id=org_id, email=f"s-{uuid.uuid4()}@c.com", role="org_admin")
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C",
                whatsapp_number=f"+9100000{phone_suffix}")
    db.add_all([usr, br]); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="Ravi", phone=f"+9190000{phone_suffix}")
    db.add_all([doc, pat]); await db.flush()
    note = TreatmentNote(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                         visit_date=date(2026, 7, 1), steps_performed="cleaning")
    task = FollowupTask(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                        status="pending", task_type="next_visit_book")
    db.add_all([note, task]); await db.commit()
    return org_id, usr, br, doc, pat


async def test_end_treatment_removes_thread_keeps_pii(db):
    org_id, usr, br, doc, pat = await _seed(db, "0061")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id, usr.id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/end-treatment", json={
                "branch_id": str(br.id), "doctor_id": str(doc.id)})
            assert r.status_code == 200, r.text
            assert r.json() == {"ended": True}
    finally:
        app.dependency_overrides.clear()

    import backend.database as _dbm
    async with _dbm.AsyncSessionLocal() as s2:
        notes = (await s2.execute(select(TreatmentNote).where(
            TreatmentNote.patient_id == pat.id))).scalars().all()
        assert notes == []  # thread gone → drops off the Treatments list
        tasks = (await s2.execute(select(FollowupTask).where(
            FollowupTask.patient_id == pat.id))).scalars().all()
        assert all(t.status == "completed" for t in tasks)  # no more calls
        p = (await s2.execute(select(Patient).where(Patient.id == pat.id))).scalar_one()
        assert p.name == "Ravi" and p.phone is not None  # PII kept


async def test_patients_delete_erases_and_hides_from_list(db):
    """Erasure lives ONLY on the Patients page (Vinay 2026-07-12):
    DELETE /patients/{id} wipes PII + notes + queued calls, and the erased
    patient never appears in the patients list again."""
    org_id, usr, br, doc, pat = await _seed(db, "0062")
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id, usr.id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.delete(f"/patients/{pat.id}",
                                params={"branch_id": str(br.id)})
            assert r.status_code == 200, r.text
            assert r.json() == {"erased": True}

            listed = await ac.get(f"/patients/branches/{br.id}/patients")
            assert all(row["id"] != str(pat.id) for row in listed.json()["patients"])
    finally:
        app.dependency_overrides.clear()

    import backend.database as _dbm
    async with _dbm.AsyncSessionLocal() as s2:
        p = (await s2.execute(select(Patient).where(Patient.id == pat.id))).scalar_one()
        assert p.name == "[erased]" and p.phone is None and p.anonymized_at is not None
        notes = (await s2.execute(select(TreatmentNote).where(
            TreatmentNote.patient_id == pat.id))).scalars().all()
        assert notes == []
        tasks = (await s2.execute(select(FollowupTask).where(
            FollowupTask.patient_id == pat.id))).scalars().all()
        assert all(t.status == "completed" for t in tasks)  # never dialed again


async def test_end_treatment_cross_branch_denied(db):
    org_id, usr, br, doc, pat = await _seed(db, "0063")
    # An org_admin from a DIFFERENT org (different branch too) must get 403.
    other_org, other_usr, other_br, _, _ = await _seed(db, "0064")
    app.dependency_overrides[get_current_user] = (
        lambda: _as_user(other_br.id, other_org, other_usr.id)
    )
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/end-treatment", json={
                "branch_id": str(br.id)})
            assert r.status_code == 403  # RULE 1
    finally:
        app.dependency_overrides.clear()
