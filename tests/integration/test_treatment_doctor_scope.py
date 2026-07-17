"""Doctor-role treatment scoping (Vinay 2026-07-16: "single doctor can see all
treatments of all doctors"). The doctor_id filter on the treatment endpoints
was an OPTIONAL client-side parameter — a doctor login could read (and write)
every doctor's threads. Server now FORCES a doctor login to its linked Doctor
row on every treatment endpoint; other roles are unchanged.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio

from backend.config import settings
from backend.models.schema import (
    Branch, Doctor, Organization, Patient, TreatmentNote, User,
)

_ALGO = "HS256"


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _jwt(role, org_id, branch_id, user_id=None):
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": user_id or str(uuid.uuid4()), "email": f"{role}@t.test", "role": role,
        "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
    }, settings.jwt_secret, algorithm=_ALGO)


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _seed(db):
    """Clinic with two doctors (d1 linked to a doctor login), one patient and
    one active treatment note per doctor."""
    org = Organization(
        name="ScopeOrg", owner_phone="+919000700091",
        owner_email=f"sc-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(org_id=org.id, name="ScopeBranch",
               whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", status="active")
    db.add(b)
    await db.flush()
    d1 = Doctor(branch_id=b.id, name="Dr Self", booking_type="appointment",
                slot_duration_minutes=30)
    d2 = Doctor(branch_id=b.id, name="Dr Other", booking_type="appointment",
                slot_duration_minutes=30)
    db.add_all([d1, d2])
    await db.flush()
    uid = uuid.uuid4()
    db.add(User(id=uid, email=f"docself-{uuid.uuid4().hex[:6]}@t.test", name="Dr Self",
                role="doctor", org_id=org.id, branch_ids=[str(b.id)]))
    await db.flush()
    d1.user_id = uid

    p1 = Patient(branch_id=b.id, name="MinePatient", phone=f"+9190{str(uuid.uuid4().int)[:8]}")
    p2 = Patient(branch_id=b.id, name="TheirsPatient", phone=f"+9190{str(uuid.uuid4().int)[:8]}")
    db.add_all([p1, p2])
    await db.flush()
    n1 = TreatmentNote(branch_id=b.id, doctor_id=d1.id, patient_id=p1.id,
                       visit_date=date.today(), steps_performed="cleaning", is_final=False)
    n2 = TreatmentNote(branch_id=b.id, doctor_id=d2.id, patient_id=p2.id,
                       visit_date=date.today(), steps_performed="filling", is_final=False)
    db.add_all([n1, n2])
    await db.commit()
    return org, b, d1, d2, uid, p1, p2, n1, n2


@pytest.mark.asyncio
async def test_doctor_list_is_forced_to_own_threads(client, db):
    org, b, d1, d2, uid, p1, p2, n1, n2 = await _seed(db)
    tok = _jwt("doctor", str(org.id), str(b.id), str(uid))

    # Even asking for the OTHER doctor's rows returns only their own.
    r = await client.get(f"/treatment/branches/{b.id}/treatment-patients",
                         params={"doctor_id": str(d2.id)}, headers=_auth(tok))
    assert r.status_code == 200, r.text
    rows = r.json()["patients"]
    assert [x["name"] for x in rows] == ["MinePatient"]
    assert all(x["doctor_id"] == str(d1.id) for x in rows)

    # Other doctor's patient's notes: forced scope yields nothing.
    r = await client.get(f"/treatment/patients/{p2.id}/treatment-notes",
                         params={"branch_id": str(b.id), "doctor_id": str(d2.id)},
                         headers=_auth(tok))
    assert r.status_code == 200
    assert r.json()["notes"] == []

    # Owner keeps the full view (unchanged for other roles).
    owner = _jwt("org_admin", str(org.id), str(b.id))
    r = await client.get(f"/treatment/branches/{b.id}/treatment-patients", headers=_auth(owner))
    assert {x["name"] for x in r.json()["patients"]} == {"MinePatient", "TheirsPatient"}


@pytest.mark.asyncio
async def test_doctor_cannot_write_other_doctors_threads(client, db):
    org, b, d1, d2, uid, p1, p2, n1, n2 = await _seed(db)
    tok = _jwt("doctor", str(org.id), str(b.id), str(uid))

    # Create a note under the other doctor -> 403.
    r = await client.post(f"/treatment/patients/{p2.id}/treatment-notes", headers=_auth(tok),
                          json={"branch_id": str(b.id), "doctor_id": str(d2.id),
                                "visit_date": date.today().isoformat(),
                                "steps_performed": "sneaky"})
    assert r.status_code == 403

    # Edit the other doctor's note -> 403.
    r = await client.patch(f"/treatment/treatment-notes/{n2.id}", headers=_auth(tok),
                           json={"branch_id": str(b.id), "doctor_id": str(d2.id),
                                 "visit_date": date.today().isoformat(),
                                 "steps_performed": "tamper"})
    assert r.status_code == 403

    # Doctor reply on the other doctor's thread -> 403.
    r = await client.post(f"/treatment/patients/{p2.id}/followups", headers=_auth(tok),
                          json={"branch_id": str(b.id), "doctor_id": str(d2.id),
                                "message": "come tomorrow"})
    assert r.status_code == 403

    # End-treatment is forced to OWN thread: other doctor's note survives.
    r = await client.post(f"/treatment/patients/{p2.id}/end-treatment", headers=_auth(tok),
                          json={"branch_id": str(b.id)})
    assert r.status_code == 200
    from sqlalchemy import select
    left = (await db.execute(select(TreatmentNote.id).where(
        TreatmentNote.id == n2.id))).scalar_one_or_none()
    assert left is not None, "doctor login must not delete another doctor's thread"
