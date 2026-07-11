"""Dashboard overhaul (2026-07-11): lifetime totals, month totals, peak-hours
grid on /analytics/overview.

Contracts:
  * lifetime counts every non-cancelled booking / answered call / primary
    patient / voice minute, with NO date window
  * month totals respect the calendar-month boundary
  * hourly_by_weekday buckets answered calls in the BRANCH timezone
  * RULE 1: a second branch's data never leaks into the first's totals
"""
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings
from backend.models.schema import Branch, CallLog, Doctor, Organization, Patient, Token

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _owner_jwt(org_id, branch_id):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "ov@x.test", "role": "org_admin",
            "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _mk_branch(db, tag):
    org = Organization(
        name=f"Org {tag}", owner_phone=f"+9190{str(uuid.uuid4().int)[:8]}",
        owner_email=f"{tag}-{uuid.uuid4().hex[:6]}@t.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name=f"B {tag}",
        whatsapp_number=f"+9156{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    await db.flush()
    doc = Doctor(branch_id=b.id, name=f"Dr {tag}", booking_type="token")
    pat = Patient(branch_id=b.id, name=f"Pat {tag}",
                  phone=f"+9192{str(uuid.uuid4().int)[:8]}", is_primary=True)
    db.add_all([doc, pat])
    await db.commit()
    return org, b, doc, pat


async def _overview(client, org, b, days=14):
    r = await client.get(
        "/analytics/overview",
        params={"branch_id": str(b.id), "days": days},
        headers={"Authorization": f"Bearer {_owner_jwt(str(org.id), str(b.id))}"},
    )
    assert r.status_code == 200, r.text
    return r.json()


async def test_lifetime_and_month_totals(client, db):
    org, b, doc, pat = await _mk_branch(db, "life")
    today = date.today()
    long_ago = today - timedelta(days=400)      # outside any period AND last month
    # Bookings: 2 recent + 1 ancient (all count) + 1 cancelled (never counts)
    def _tok(n, d, status):
        return Token(branch_id=b.id, doctor_id=doc.id, patient_id=pat.id,
                     token_number=n, date=d, status=status, source="voice")

    db.add_all([
        _tok(1, today, "confirmed"),
        _tok(2, today, "attended"),
        _tok(3, long_ago, "attended"),
        _tok(4, today, "cancelled_by_patient"),
    ])
    now = datetime.now(timezone.utc)
    # Calls: 1 this month (120s) + 1 ancient (300s) + 1 unanswered (never counts)
    db.add_all([
        CallLog(branch_id=b.id, call_type="inbound", answered=True,
                started_at=now, duration_seconds=120, booking_made=False),
        CallLog(branch_id=b.id, call_type="inbound", answered=True,
                started_at=now - timedelta(days=400), duration_seconds=300,
                booking_made=False),
        CallLog(branch_id=b.id, call_type="inbound", answered=False,
                started_at=now, duration_seconds=0, booking_made=False),
    ])
    # Fixture already made 1 primary patient; add 1 family member (non-primary
    # — must not count in lifetime.patients).
    db.add(Patient(branch_id=b.id, name="P2", phone=pat.phone, is_primary=False))
    await db.commit()

    body = await _overview(client, org, b)
    lt = body["lifetime"]
    assert lt["bookings"] == 3          # cancelled excluded, ancient included
    assert lt["calls"] == 2             # unanswered excluded
    assert lt["patients"] == 1          # primary only
    assert lt["minutes"] == 7           # (120+300+0)//60

    m = body["month"]
    assert m["bookings"] >= 2           # the two today-bookings (ancient excluded)
    assert m["calls"] == 1              # only this month's answered call
    # fixture patient + family member both created "now" -> this month
    assert m["new_patients"] == 2


async def test_hourly_grid_buckets_in_branch_tz(client, db):
    org, b, doc, pat = await _mk_branch(db, "hours")
    # 10:30 IST today == 05:00 UTC. Branch default tz Asia/Kolkata.
    ist_morning_utc = datetime.now(timezone.utc).replace(
        hour=5, minute=0, second=0, microsecond=0
    )
    db.add(CallLog(branch_id=b.id, call_type="inbound", answered=True,
                   started_at=ist_morning_utc, duration_seconds=60,
                   booking_made=False))
    await db.commit()

    body = await _overview(client, org, b)
    cells = body["hourly_by_weekday"]
    assert cells, "expected at least one heatmap cell"
    hit = [c for c in cells if c["calls"] >= 1]
    assert any(c["hour"] == 10 for c in hit), (
        f"05:00 UTC must bucket as 10:xx IST, got {hit}"
    )
    for c in cells:
        assert 0 <= c["weekday"] <= 6


async def test_rule1_lifetime_isolated_between_branches(client, db):
    org_a, b_a, doc_a, pat_a = await _mk_branch(db, "iso-a")
    org_b, b_b, doc_b, pat_b = await _mk_branch(db, "iso-b")
    db.add(Token(branch_id=b_a.id, doctor_id=doc_a.id, patient_id=pat_a.id,
                 token_number=1, date=date.today(), status="confirmed", source="voice"))
    await db.commit()

    body_b = await _overview(client, org_b, b_b)
    assert body_b["lifetime"]["bookings"] == 0
    assert body_b["lifetime"]["calls"] == 0
    assert body_b["lifetime"]["patients"] == 1  # only its own fixture patient
