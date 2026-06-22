"""Integration tests for the treatment-notes router (Task 3, M1).

Covers:
  - test_create_and_list_treatment_note — POST creates a note, GET timeline returns it
  - test_end_keyword_closes_treatment — next_steps="end" sets is_final=True
  - test_cross_branch_note_denied — a user scoped to another branch gets 403 (RULE 1)

Seed notes (vs. the brief's skeleton — the real schema enforces these via create_all):
  - Branch.org_id is a RESTRICT FK to organizations.id → each test seeds an
    Organization row first.
  - Branch.whatsapp_number is NOT NULL + unique → seeded (brief used did_number,
    which is nullable; whatsapp_number is the required column).
  - Doctor.booking_type is NOT NULL → seeded ("token").
  - CurrentUser.__init__ requires a jti arg → _as_user passes one.
"""
import uuid
from datetime import date
import pytest
from httpx import AsyncClient, ASGITransport
from backend.main import app
from backend.models.schema import Branch, Doctor, Patient, Organization, User
from backend.middleware.auth_middleware import get_current_user, CurrentUser


def _as_user(branch_id, org_id, role="org_admin", user_id=None):
    return CurrentUser(user_id=str(user_id or uuid.uuid4()), email="d@c.com", role=role,
                       org_id=str(org_id), branch_ids=[str(branch_id)], is_admin=False,
                       jti=str(uuid.uuid4()))


def _org(org_id):
    return Organization(id=org_id, name="Org", owner_phone="+919000099001",
                        owner_email=f"owner-{org_id}@c.com", plan="clinic")


def _user(org_id):
    # created_by_user_id is a FK to users.id — seed a real staff row so the
    # note INSERT does not trip the FK (brief's _as_user used a random UUID).
    return User(id=uuid.uuid4(), org_id=org_id, email=f"staff-{uuid.uuid4()}@c.com",
                role="org_admin")


@pytest.mark.asyncio
async def test_create_and_list_treatment_note(db):
    org_id = uuid.uuid4()
    db.add(_org(org_id)); await db.flush()
    usr = _user(org_id)
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", whatsapp_number="+910000000010")
    db.add_all([usr, br]); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000010")
    db.add_all([doc, pat]); await db.commit()

    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id, user_id=usr.id)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/treatment-notes", json={
                "doctor_id": str(doc.id), "branch_id": str(br.id),
                "visit_date": "2026-06-22", "steps_performed": "cleaning",
                "next_steps": "floss", "next_reporting_date": "2026-06-25"})
            assert r.status_code == 201, r.text
            assert r.json()["is_final"] is False

            r2 = await ac.get(f"/treatment/patients/{pat.id}/treatment-notes",
                              params={"branch_id": str(br.id)})
            assert r2.status_code == 200
            body = r2.json()
            assert body["treatment_status"] == "active"
            assert len(body["notes"]) == 1
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_end_keyword_closes_treatment(db):
    org_id = uuid.uuid4()
    db.add(_org(org_id)); await db.flush()
    usr = _user(org_id)
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", whatsapp_number="+910000000011")
    db.add_all([usr, br]); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A", booking_type="token")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000011")
    db.add_all([doc, pat]); await db.commit()
    app.dependency_overrides[get_current_user] = lambda: _as_user(br.id, org_id, user_id=usr.id)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/treatment-notes", json={
                "doctor_id": str(doc.id), "branch_id": str(br.id),
                "visit_date": "2026-06-22", "next_steps": "end"})
            assert r.json()["is_final"] is True
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_cross_branch_note_denied(db):
    org_id = uuid.uuid4()
    other_org_id = uuid.uuid4()
    db.add_all([_org(org_id), _org(other_org_id)]); await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org_id, name="C", whatsapp_number="+910000000012")
    other = Branch(id=uuid.uuid4(), org_id=other_org_id, name="O", whatsapp_number="+910000000013")
    db.add_all([br, other]); await db.flush()
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000012")
    db.add(pat); await db.commit()
    # User scoped to `other` must not write a note on br's patient.
    app.dependency_overrides[get_current_user] = lambda: _as_user(other.id, other_org_id)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://t") as ac:
            r = await ac.post(f"/treatment/patients/{pat.id}/treatment-notes", json={
                "doctor_id": str(uuid.uuid4()), "branch_id": str(br.id),
                "visit_date": "2026-06-22"})
            assert r.status_code == 403
    finally:
        app.dependency_overrides.clear()
