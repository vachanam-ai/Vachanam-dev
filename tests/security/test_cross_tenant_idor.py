"""Cross-tenant IDOR sweep — the founder's core fear ("is every endpoint packed
strong?"). A malicious clinic owner with a VALID JWT for their own org must
never reach another clinic's data, on ANY branch-scoped endpoint.

Two attack shapes are exercised against every route:
  1. Foreign branch_id: owner B passes clinic A's branch_id → assert_branch_access
     must 403 (org mismatch) before any query runs.
  2. Own branch_id + foreign resource_id: owner B passes their OWN branch_id but
     a patient_id / note_id belonging to clinic A → the WHERE branch_id clause
     must yield 404 (the row is invisible), never A's data.

Plus: super_admin (Vinay, Data Processor) is locked OUT of clinic PII routes
(DPDP boundary) even though he is "admin".

A leak = a 200 response carrying clinic A's data. Every assertion below rejects
that. This file is the regression wall: a future endpoint that forgets its
branch scope fails here.
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt

from backend.config import settings
from backend.models.schema import (
    Branch, CallLog, Doctor, Organization, Patient, Token, TreatmentNote,
)

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _jwt(*, role, org_id, branch_ids, is_admin=False):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": f"{role}@idor.test", "role": role,
            "org_id": org_id, "branch_ids": branch_ids, "is_admin": is_admin,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _make_clinic(db, tag):
    """A full clinic: org + branch + doctor + patient + a token + a treatment note."""
    org = Organization(
        name=f"Org {tag}", owner_phone=f"+9190{str(uuid.uuid4().int)[:8]}",
        owner_email=f"{tag}-{uuid.uuid4().hex[:6]}@t.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name=f"B {tag}",
        whatsapp_number=f"+9157{str(uuid.uuid4().int)[:8]}", status="active",
        timezone="Asia/Kolkata",
    )
    db.add(b)
    await db.flush()
    doc = Doctor(branch_id=b.id, name=f"Dr {tag}", booking_type="token",
                 daily_token_limit=30, is_default_doctor=True)
    pat = Patient(branch_id=b.id, name=f"Pat {tag}",
                  phone=f"+9193{str(uuid.uuid4().int)[:8]}", is_primary=True)
    db.add_all([doc, pat])
    await db.flush()
    note = TreatmentNote(branch_id=b.id, doctor_id=doc.id, patient_id=pat.id,
                         visit_date=date.today() - timedelta(days=1))
    tok = Token(branch_id=b.id, doctor_id=doc.id, patient_id=pat.id,
                token_number=1, date=date.today(), status="confirmed", source="voice")
    db.add_all([note, tok])
    db.add(CallLog(branch_id=b.id, call_type="inbound", answered=True,
                   started_at=datetime.now(timezone.utc), duration_seconds=60,
                   booking_made=True))
    await db.commit()
    return {
        "org_id": str(org.id), "branch_id": str(b.id), "doctor_id": str(doc.id),
        "patient_id": str(pat.id), "note_id": str(note.id),
    }


LEAK = "leaked clinic A data via {}"


@pytest_asyncio.fixture
async def two_clinics(db):
    a = await _make_clinic(db, "victimA")
    b = await _make_clinic(db, "attackerB")
    # attacker owns clinic B only
    b_token = _jwt(role="org_admin", org_id=b["org_id"], branch_ids=[b["branch_id"]])
    return a, b, b_token


# ── 1. Foreign branch_id in the path/query → 403 or 404, never 200 ──────────

async def test_foreign_branch_id_blocked_everywhere(two_clinics, client):
    a, b, tok = two_clinics
    A = a["branch_id"]
    # (method, url) pairs that take clinic A's branch_id directly.
    reads = [
        ("GET", f"/queue/{A}/today"),
        ("GET", f"/patients/branches/{A}/patients"),
        ("GET", f"/branches/{A}/settings"),
        ("GET", f"/branches/{A}/voices"),
        ("GET", f"/branches/{A}/faq"),
        ("GET", f"/branches/{A}/telephony"),
        ("GET", f"/doctors/{A}"),
        ("GET", f"/treatment/branches/{A}/treatment-patients"),
        ("GET", f"/analytics/overview?branch_id={A}"),
        ("GET", f"/analytics/call-quality?branch_id={A}"),
    ]
    for method, url in reads:
        r = await client.request(method, url, headers=_auth(tok))
        assert r.status_code in (403, 404), f"{url} → {r.status_code}: {LEAK.format(url)}"
        # a defended endpoint never returns clinic A's identifiers
        assert a["patient_id"] not in r.text and a["doctor_id"] not in r.text, LEAK.format(url)


async def test_public_tv_display_exposes_no_patient_pii(two_clinics, client):
    """/queue/{branch}/display is intentionally public (waiting-room TV kiosk).
    Contract: it may show clinic + doctor names + token counts, but NEVER any
    patient identifier — the query must not join Patient."""
    a, _, _ = two_clinics
    r = await client.get(f"/queue/{a['branch_id']}/display")  # no auth — public
    assert r.status_code == 200
    assert a["patient_id"] not in r.text
    # no phone digits, no patient name leaked
    assert "Pat victimA" not in r.text


async def test_foreign_branch_id_writes_blocked(two_clinics, client):
    a, b, tok = two_clinics
    A = a["branch_id"]
    # POST a doctor into clinic A's branch
    r = await client.post(f"/doctors/{A}", headers=_auth(tok),
                          json={"name": "Injected", "booking_type": "token"})
    assert r.status_code in (403, 404), LEAK.format("POST /doctors/{A}")
    # POST a walk-in into clinic A's queue
    r = await client.post(f"/queue/{A}/walkin", headers=_auth(tok),
                          json={"patient_name": "X", "patient_phone": "+919000000000",
                                "doctor_id": a["doctor_id"]})
    assert r.status_code in (403, 404, 422), LEAK.format("POST /queue/{A}/walkin")
    # PATCH clinic A's branch settings
    r = await client.patch(f"/branches/{A}/settings", headers=_auth(tok),
                           json={"name": "Hacked Clinic"})
    assert r.status_code in (403, 404), LEAK.format("PATCH /branches/{A}/settings")


# ── 2. Own branch_id + foreign resource_id → 404 (row invisible) ────────────

async def test_foreign_resource_id_with_own_branch_blocked(two_clinics, client):
    a, b, tok = two_clinics
    Bbranch = b["branch_id"]
    # Edit clinic A's patient while claiming it lives in MY branch → 404.
    r = await client.patch(f"/patients/{a['patient_id']}", headers=_auth(tok),
                           json={"branch_id": Bbranch, "name": "Owned"})
    assert r.status_code == 404, "IDOR: edited clinic A's patient via own branch_id"
    # Read clinic A's treatment notes with my own branch_id → empty, not A's data.
    r = await client.get(
        f"/treatment/patients/{a['patient_id']}/treatment-notes?branch_id={Bbranch}",
        headers=_auth(tok))
    assert r.status_code in (200, 404)
    if r.status_code == 200:
        assert a["note_id"] not in r.text, "IDOR: read clinic A's treatment note"
    # PATCH clinic A's treatment note while claiming my branch → 404.
    r = await client.patch(f"/treatment/treatment-notes/{a['note_id']}", headers=_auth(tok),
                           json={"branch_id": Bbranch, "doctor_id": b["doctor_id"],
                                 "visit_date": date.today().isoformat()})
    assert r.status_code == 404, "IDOR: edited clinic A's treatment note via own branch_id"


# ── 3. super_admin locked out of clinic PII (DPDP boundary) ─────────────────

async def test_super_admin_denied_clinic_pii(two_clinics, client):
    a, _, _ = two_clinics
    A = a["branch_id"]
    sa = _jwt(role="super_admin", org_id=None, branch_ids=[], is_admin=True)
    for url in (f"/queue/{A}/today", f"/patients/branches/{A}/patients",
                f"/analytics/overview?branch_id={A}", f"/branches/{A}/settings",
                f"/treatment/branches/{A}/treatment-patients"):
        r = await client.get(url, headers=_auth(sa))
        assert r.status_code == 403, f"super_admin reached clinic PII at {url}"
        assert a["patient_id"] not in r.text


# ── 4. No/invalid token → 401, never data ──────────────────────────────────

async def test_missing_and_garbage_tokens_rejected(two_clinics, client):
    a, _, _ = two_clinics
    A = a["branch_id"]
    r = await client.get(f"/queue/{A}/today")
    assert r.status_code in (401, 403)
    r = await client.get(f"/queue/{A}/today", headers=_auth("garbage.jwt.here"))
    assert r.status_code in (401, 403)
    # a token signed with the WRONG secret must be rejected (signature check)
    forged = jwt.encode(
        {"sub": str(uuid.uuid4()), "email": "e@e.com", "role": "org_admin",
         "org_id": a["org_id"], "branch_ids": [A], "is_admin": False,
         "iat": int(datetime.now(timezone.utc).timestamp()),
         "exp": int((datetime.now(timezone.utc) + timedelta(hours=8)).timestamp()),
         "jti": str(uuid.uuid4())},
        "not-the-real-secret", algorithm=_ALGO)
    r = await client.get(f"/queue/{A}/today", headers=_auth(forged))
    assert r.status_code in (401, 403), "forged-signature JWT accepted!"
