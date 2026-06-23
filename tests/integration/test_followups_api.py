"""Integration tests for the follow-up thread router (Task 7, M2).

Covers:
  - test_doctor_reply_creates_advice_task — POST creates a doctor_advice FollowupTask
  - test_list_followups_thread_ordered — GET returns only next_visit_book/doctor_advice
    rows for the patient+branch, ordered by created_at asc
  - test_cross_branch_followup_denied — a user scoped to another branch gets 403 (RULE 1)

Seed notes (vs. the brief's skeleton — the real schema enforces these via create_all):
  - Branch.org_id is a RESTRICT FK to organizations.id → each test seeds an
    Organization row first.
  - Branch.whatsapp_number is NOT NULL + unique → seeded (brief used did_number,
    which is nullable; whatsapp_number is the required column).
  - Doctor.booking_type is NOT NULL → seeded ("token").
  - CurrentUser.__init__ requires a jti arg → _u passes one.
  - FollowupTask.created_by_user_id is a FK to users.id → seed a real User row.
"""
import uuid
from datetime import date

import pytest
from httpx import AsyncClient, ASGITransport
from sqlalchemy import select

from backend.main import app
from backend.models.schema import (
    Branch, Doctor, Patient, Organization, User, FollowupTask,
)
from backend.middleware.auth_middleware import get_current_user, CurrentUser


def _u(b, o, user_id=None):
    return CurrentUser(user_id=str(user_id or uuid.uuid4()), email="d@c", role="doctor",
                       org_id=str(o), branch_ids=[str(b)], is_admin=False,
                       jti=str(uuid.uuid4()))


def _org(org_id):
    return Organization(id=org_id, name="Org", owner_phone="+919000099040",
                        owner_email=f"owner-{org_id}@c.com", plan="clinic")


def _user(org_id):
    return User(id=uuid.uuid4(), org_id=org_id, email=f"staff-{uuid.uuid4()}@c.com",
                role="doctor")


@pytest.mark.asyncio
async def test_doctor_reply_creates_advice_task(db):
    o = uuid.uuid4()
    db.add(_org(o)); await db.flush()
    usr = _user(o)
    br = Branch(id=uuid.uuid4(), org_id=o, name="C", whatsapp_number="+910000000040")
    db.add_all([usr, br]); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000040")
    db.add_all([doc, pat]); await db.commit()
    app.dependency_overrides[get_current_user] = lambda: _u(br.id, o, user_id=usr.id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/followups", json={
                "branch_id": str(br.id), "doctor_id": str(doc.id),
                "message": "Take the prescribed painkiller twice daily."})
            assert r.status_code == 201, r.text
        task = (await db.execute(
            select(FollowupTask).where(FollowupTask.patient_id == pat.id))).scalar_one()
        assert task.task_type == "doctor_advice"
        assert task.what_to_ask == "Take the prescribed painkiller twice daily."
        assert task.status == "pending"
        assert task.channel == "voice"
        assert task.scheduled_date == date.today()
        assert task.created_by_user_id == usr.id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_list_followups_thread_ordered(db):
    o = uuid.uuid4()
    db.add(_org(o)); await db.flush()
    usr = _user(o)
    br = Branch(id=uuid.uuid4(), org_id=o, name="C", whatsapp_number="+910000000041")
    db.add_all([usr, br]); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000041")
    db.add_all([doc, pat]); await db.flush()
    # In-thread: next_visit_book + doctor_advice; out-of-thread: post_appt_check (hidden).
    t_book = FollowupTask(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                          task_type="next_visit_book", channel="voice",
                          what_to_ask="Come back next week", status="pending",
                          scheduled_date=date.today())
    t_adv = FollowupTask(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                         task_type="doctor_advice", channel="voice",
                         what_to_ask="Rest the jaw", status="pending",
                         scheduled_date=date.today())
    t_hidden = FollowupTask(branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                            task_type="post_appt_check", channel="voice",
                            status="pending", scheduled_date=date.today())
    db.add(t_book); await db.flush()
    db.add(t_adv); await db.flush()
    db.add(t_hidden); await db.commit()
    app.dependency_overrides[get_current_user] = lambda: _u(br.id, o, user_id=usr.id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.get(f"/treatment/patients/{pat.id}/followups",
                             params={"branch_id": str(br.id)})
            assert r.status_code == 200, r.text
            thread = r.json()["thread"]
        assert [m["task_type"] for m in thread] == ["next_visit_book", "doctor_advice"]
        assert thread[0]["message"] == "Come back next week"
        assert thread[1]["message"] == "Rest the jaw"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cross_branch_doctor_id_rejected_on_reply(db):
    """RULE 1 write-hygiene: doctor_reply with a doctor_id from another branch is
    rejected with 404, even when the user's branch_access is legitimate."""
    o = uuid.uuid4()
    other_o = uuid.uuid4()
    db.add_all([_org(o), _org(other_o)]); await db.flush()
    usr = _user(o)
    br = Branch(id=uuid.uuid4(), org_id=o, name="C", whatsapp_number="+910000000044")
    other = Branch(id=uuid.uuid4(), org_id=other_o, name="O", whatsapp_number="+910000000045")
    db.add_all([usr, br, other]); await db.flush()
    other_doc = Doctor(id=uuid.uuid4(), branch_id=other.id, name="Dr Out", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000044")
    db.add_all([other_doc, pat]); await db.commit()
    app.dependency_overrides[get_current_user] = lambda: _u(br.id, o, user_id=usr.id)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/followups", json={
                "branch_id": str(br.id), "doctor_id": str(other_doc.id),
                "message": "x"})
            assert r.status_code == 404, r.text
            assert r.json()["detail"] == "doctor not found in branch"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cross_branch_followup_denied(db):
    o = uuid.uuid4()
    other_o = uuid.uuid4()
    db.add_all([_org(o), _org(other_o)]); await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=o, name="C", whatsapp_number="+910000000042")
    other = Branch(id=uuid.uuid4(), org_id=other_o, name="O", whatsapp_number="+910000000043")
    db.add_all([br, other]); await db.flush()
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000042")
    db.add(pat); await db.commit()
    # User scoped to `other` must not reply on br's patient.
    app.dependency_overrides[get_current_user] = lambda: _u(other.id, other_o)
    try:
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/followups", json={
                "branch_id": str(br.id), "doctor_id": str(uuid.uuid4()),
                "message": "x"})
            assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
