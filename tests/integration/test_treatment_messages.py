"""Patient messages inside the treatment thread (Vinay 2026-07-17): a treating
patient's voice-agent message must (1) appear in their treatment thread,
(2) light the Treatments list row with an unread count (WhatsApp model), and
(3) clear when the thread is opened — via mark-read, which touches ONLY
read_at (the dashboard's pending/done callback workflow stays untouched).
RULE 1: everything branch-scoped.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import (
    Branch, Doctor, Organization, Patient, PatientMessage, TreatmentNote, User,
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


async def _seed_clinic(db, tag):
    org = Organization(
        name=f"MsgOrg{tag}", owner_phone=f"+9190007001{tag}",
        owner_email=f"msg{tag}-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(org_id=org.id, name=f"MsgBranch{tag}",
               whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", status="active")
    db.add(b)
    await db.flush()
    d = Doctor(branch_id=b.id, name=f"Dr Msg{tag}", booking_type="appointment",
               slot_duration_minutes=30)
    db.add(d)
    await db.flush()
    p = Patient(branch_id=b.id, name=f"MsgPatient{tag}",
                phone=f"+9190{str(uuid.uuid4().int)[:8]}")
    db.add(p)
    await db.flush()
    db.add(TreatmentNote(branch_id=b.id, doctor_id=d.id, patient_id=p.id,
                         visit_date=date.today(), steps_performed="scaling",
                         is_final=False))
    await db.commit()
    return org, b, d, p


@pytest.mark.asyncio
async def test_message_appears_in_thread_and_lights_the_row(client, db):
    org, b, d, p = await _seed_clinic(db, "1")
    db.add(PatientMessage(branch_id=b.id, patient_id=p.id, caller_phone=p.phone,
                          message="tell doctor the swelling is back", urgent=True))
    await db.commit()
    tok = _jwt("org_admin", str(org.id), str(b.id))

    # Treatments list: the row carries the unread count + last message time.
    r = await client.get(f"/treatment/branches/{b.id}/treatment-patients",
                         headers=_auth(tok))
    assert r.status_code == 200, r.text
    row = next(x for x in r.json()["patients"] if x["patient_id"] == str(p.id))
    assert row["unread_messages"] == 1
    assert row["last_message_at"] is not None

    # The message is IN the treatment thread, patient-side, unread.
    r = await client.get(f"/treatment/patients/{p.id}/followups",
                         params={"branch_id": str(b.id), "doctor_id": str(d.id)},
                         headers=_auth(tok))
    assert r.status_code == 200
    msgs = [t for t in r.json()["thread"] if t["task_type"] == "patient_message"]
    assert len(msgs) == 1
    assert msgs[0]["response"] == "tell doctor the swelling is back"
    assert msgs[0]["unread"] is True
    assert msgs[0]["urgent"] is True


@pytest.mark.asyncio
async def test_mark_read_clears_highlight_idempotently_and_keeps_status(client, db):
    org, b, d, p = await _seed_clinic(db, "2")
    m = PatientMessage(branch_id=b.id, patient_id=p.id, caller_phone=p.phone,
                       message="payment question for the clinic")
    db.add(m)
    await db.commit()
    mid = m.id
    tok = _jwt("org_admin", str(org.id), str(b.id))

    r = await client.post(f"/treatment/patients/{p.id}/messages/mark-read",
                          json={"branch_id": str(b.id)}, headers=_auth(tok))
    assert r.status_code == 200 and r.json()["marked"] == 1

    # Unread count drops to zero; thread item flips to read.
    r = await client.get(f"/treatment/branches/{b.id}/treatment-patients",
                         headers=_auth(tok))
    row = next(x for x in r.json()["patients"] if x["patient_id"] == str(p.id))
    assert row["unread_messages"] == 0 and row["last_message_at"] is None
    r = await client.get(f"/treatment/patients/{p.id}/followups",
                         params={"branch_id": str(b.id)}, headers=_auth(tok))
    msg = next(t for t in r.json()["thread"] if t["task_type"] == "patient_message")
    assert msg["unread"] is False

    # Idempotent: second call matches nothing.
    r = await client.post(f"/treatment/patients/{p.id}/messages/mark-read",
                          json={"branch_id": str(b.id)}, headers=_auth(tok))
    assert r.status_code == 200 and r.json()["marked"] == 0

    # read is NOT done: the dashboard callback workflow is untouched.
    db.expire_all()
    fresh = (await db.execute(
        select(PatientMessage).where(PatientMessage.id == mid)
    )).scalar_one()
    assert fresh.status == "pending" and fresh.read_at is not None


@pytest.mark.asyncio
async def test_rule1_messages_never_cross_branches(client, db):
    org_a, b_a, d_a, p_a = await _seed_clinic(db, "3")
    org_b, b_b, d_b, p_b = await _seed_clinic(db, "4")
    db.add(PatientMessage(branch_id=b_b.id, patient_id=p_b.id,
                          caller_phone=p_b.phone, message="other clinic secret"))
    await db.commit()
    tok_a = _jwt("org_admin", str(org_a.id), str(b_a.id))

    # Branch A's list shows zero unread — B's message never leaks.
    r = await client.get(f"/treatment/branches/{b_a.id}/treatment-patients",
                         headers=_auth(tok_a))
    assert all(x["unread_messages"] == 0 for x in r.json()["patients"])

    # A's token cannot mark-read (or even address) B's patient.
    r = await client.post(f"/treatment/patients/{p_b.id}/messages/mark-read",
                          json={"branch_id": str(b_b.id)}, headers=_auth(tok_a))
    assert r.status_code == 403
    r = await client.post(f"/treatment/patients/{p_b.id}/messages/mark-read",
                          json={"branch_id": str(b_a.id)}, headers=_auth(tok_a))
    assert r.status_code == 404  # patient not in A's branch
    fresh = (await db.execute(
        select(PatientMessage).where(PatientMessage.branch_id == b_b.id)
    )).scalar_one()
    assert fresh.read_at is None
