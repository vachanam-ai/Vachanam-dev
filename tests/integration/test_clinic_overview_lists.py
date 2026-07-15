"""Vinay 2026-07-15 clinic features:
- Patients page: upcoming appointments (next 15 days) + doctor/date filters.
- Doctor-leave page: doctors on leave (next 30 days), grouped into ranges.
Both read-only, RULE 1 branch-scoped.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio

from backend.config import settings
from backend.models.schema import (
    Branch, Doctor, DoctorUnavailability, Organization, Patient, Token,
)

_ALGO = "HS256"


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _owner(org_id, branch_id):
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": str(uuid.uuid4()), "email": "o@t.test", "role": "org_admin",
        "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
    }, settings.jwt_secret, algorithm=_ALGO)


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _clinic(db):
    org = Organization(
        name="OvOrg", owner_phone="+919000700090",
        owner_email=f"ov-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="OvBranch",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    await db.commit()
    return org, b


async def _doctor(db, b, name):
    d = Doctor(branch_id=b.id, name=name, booking_type="appointment",
               slot_duration_minutes=30)
    db.add(d)
    await db.flush()
    return d


async def _booking(db, b, d, day, when=None, name="Ravi"):
    p = Patient(branch_id=b.id, name=name, phone=f"+9190{str(uuid.uuid4().int)[:8]}")
    db.add(p)
    await db.flush()
    db.add(Token(branch_id=b.id, doctor_id=d.id, patient_id=p.id, date=day,
                 appointment_time=when, source="voice", status="confirmed"))
    await db.commit()


# ── upcoming appointments ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_upcoming_window_and_filters(client, db):
    org, b = await _clinic(db)
    d1 = await _doctor(db, b, "Dr A")
    d2 = await _doctor(db, b, "Dr B")
    today = date.today()
    await _booking(db, b, d1, today + timedelta(days=1), time(10, 0), "Ravi")
    await _booking(db, b, d2, today + timedelta(days=2), time(11, 0), "Sita")
    await _booking(db, b, d1, today + timedelta(days=40), time(9, 0), "Late")  # outside 15d

    tok = _owner(str(org.id), str(b.id))
    r = await client.get(f"/patients/branches/{b.id}/upcoming", headers=_auth(tok))
    assert r.status_code == 200, r.text
    appts = r.json()["appointments"]
    assert len(appts) == 2  # 40-day one excluded
    assert appts[0]["date"] <= appts[1]["date"]  # sorted

    # doctor filter
    r2 = await client.get(f"/patients/branches/{b.id}/upcoming",
                          params={"doctor_id": str(d1.id)}, headers=_auth(tok))
    assert [a["doctor_name"] for a in r2.json()["appointments"]] == ["Dr A"]

    # date filter
    r3 = await client.get(f"/patients/branches/{b.id}/upcoming",
                          params={"on_date": (today + timedelta(days=2)).isoformat()},
                          headers=_auth(tok))
    assert [a["patient_name"] for a in r3.json()["appointments"]] == ["Sita"]


@pytest.mark.asyncio
async def test_upcoming_branch_isolated(client, db):
    org1, b1 = await _clinic(db)
    org2, b2 = await _clinic(db)
    tok1 = _owner(str(org1.id), str(b1.id))
    r = await client.get(f"/patients/branches/{b2.id}/upcoming", headers=_auth(tok1))
    assert r.status_code in (403, 404)


# ── upcoming leave ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_leave_groups_consecutive_dates(client, db):
    org, b = await _clinic(db)
    d = await _doctor(db, b, "Dr Leave")
    today = date.today()
    # 3-day run + a gap + a single day
    for off in (3, 4, 5, 9):
        db.add(DoctorUnavailability(branch_id=b.id, doctor_id=d.id,
                                    date=today + timedelta(days=off)))
    await db.commit()

    tok = _owner(str(org.id), str(b.id))
    r = await client.get(f"/availability/{b.id}/leave/upcoming", headers=_auth(tok))
    assert r.status_code == 200, r.text
    leave = r.json()["leave"]
    assert len(leave) == 2  # [3-5] and [9]
    spans = {(row["from"], row["to"]) for row in leave}
    assert ((today + timedelta(days=3)).isoformat(),
            (today + timedelta(days=5)).isoformat()) in spans
    assert ((today + timedelta(days=9)).isoformat(),
            (today + timedelta(days=9)).isoformat()) in spans


@pytest.mark.asyncio
async def test_leave_excludes_beyond_window_and_isolates(client, db):
    org, b = await _clinic(db)
    d = await _doctor(db, b, "Dr X")
    today = date.today()
    db.add(DoctorUnavailability(branch_id=b.id, doctor_id=d.id,
                               date=today + timedelta(days=45)))  # outside 30d
    await db.commit()
    tok = _owner(str(org.id), str(b.id))
    r = await client.get(f"/availability/{b.id}/leave/upcoming", headers=_auth(tok))
    assert r.json()["leave"] == []

    org2, b2 = await _clinic(db)
    r2 = await client.get(f"/availability/{b2.id}/leave/upcoming",
                          headers=_auth(_owner(str(org.id), str(b.id))))
    assert r2.status_code in (403, 404)


# ── Doctor-scoped views (Vinay 2026-07-15) ───────────────────────────────────


def _doctor_jwt(org_id, branch_id, user_id):
    now = datetime.now(timezone.utc)
    return jwt.encode({
        "sub": user_id, "email": "doc@t.test", "role": "doctor",
        "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
    }, settings.jwt_secret, algorithm=_ALGO)


@pytest.mark.asyncio
async def test_doctor_upcoming_is_forced_to_own_patients(client, db):
    from backend.models.schema import User

    org, b = await _clinic(db)
    d1 = await _doctor(db, b, "Dr Self")
    d2 = await _doctor(db, b, "Dr Other")
    uid = uuid.uuid4()
    db.add(User(id=uid, email="docself@t.test", name="Dr Self", role="doctor",
                org_id=org.id, branch_ids=[str(b.id)]))
    await db.flush()
    d1.user_id = uid
    await db.commit()

    today = date.today()
    await _booking(db, b, d1, today + timedelta(days=1), time(10, 0), "Mine")
    await _booking(db, b, d2, today + timedelta(days=1), time(11, 0), "Theirs")

    tok = _doctor_jwt(str(org.id), str(b.id), str(uid))
    # even if the doctor passes the OTHER doctor's id, they get only their own
    r = await client.get(f"/patients/branches/{b.id}/upcoming",
                         params={"doctor_id": str(d2.id)}, headers=_auth(tok))
    assert r.status_code == 200, r.text
    names = [a["patient_name"] for a in r.json()["appointments"]]
    assert names == ["Mine"]


@pytest.mark.asyncio
async def test_queue_exposes_doctor_user_id_for_filtering(client, db):
    from backend.models.schema import User

    org, b = await _clinic(db)
    d = await _doctor(db, b, "Dr Q")
    uid = uuid.uuid4()
    db.add(User(id=uid, email="docq@t.test", name="Dr Q", role="doctor",
                org_id=org.id, branch_ids=[str(b.id)]))
    await db.flush()
    d.user_id = uid
    await db.commit()
    await _booking(db, b, d, date.today(), time(10, 0), "QPat")

    tok = _owner(str(org.id), str(b.id))
    r = await client.get(f"/queue/{b.id}/today", headers=_auth(tok))
    assert r.status_code == 200, r.text
    docs = r.json()["doctors"]
    assert any(x.get("doctor_user_id") == str(uid) for x in docs)
