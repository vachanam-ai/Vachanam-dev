"""Queue-status feature (2026-07-04, gap B — token doctors only).

Voice: get_queue_status tool → queue_position_by_phone (caller's position,
"now serving" derived from attendance marks — no new state).
TV: GET /queue/{branch_id}/display is PUBLIC (waiting-room TV) and must
expose ZERO patient PII — token numbers + doctor names only.
"""
import uuid
from datetime import date

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from agent.tools.booking_tools import queue_position_by_phone
from backend.models.schema import Branch, Doctor, Organization, Patient, Token

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def clinic(db):
    """Branch with one token doctor and one slot doctor; today's queue:
    tokens 1-2 attended, 3 no_show, 4-6 confirmed. Caller 9666000004 owns
    token 5 → now_serving=2, one confirmed token (4) ahead."""
    org = Organization(
        name="Q Org", owner_phone="+919000777001",
        owner_email=f"q-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="Q Clinic",
        whatsapp_number=f"+9178{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(branch)
    await db.flush()
    tok_doc = Doctor(branch_id=branch.id, name="Dr Queue", booking_type="token",
                     daily_token_limit=30)
    slot_doc = Doctor(branch_id=branch.id, name="Dr Slot", booking_type="appointment")
    db.add_all([tok_doc, slot_doc])
    await db.flush()

    today = date.today()
    statuses = {1: "attended", 2: "attended", 3: "no_show",
                4: "confirmed", 5: "confirmed", 6: "confirmed"}
    caller_patient = None
    for n, status in statuses.items():
        p = Patient(branch_id=branch.id, name=f"P{n}",
                    phone=f"+91966600000{n}", is_primary=True)
        db.add(p)
        await db.flush()
        if n == 5:
            caller_patient = p
        db.add(Token(branch_id=branch.id, doctor_id=tok_doc.id, patient_id=p.id,
                     date=today, token_number=n, status=status, source="voice"))
    await db.commit()
    return {
        "branch_id": str(branch.id), "branch_uuid": branch.id,
        "tok_doc_id": tok_doc.id, "caller_phone": caller_patient.phone,
    }


async def test_display_is_public_and_pii_free(clinic, client):
    """No auth header → 200. now_serving = max attended (2); waiting counts
    only confirmed (3). No patient name anywhere in the payload."""
    r = await client.get(f"/queue/{clinic['branch_id']}/display")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["clinic_name"] == "Q Clinic"
    boards = {d["doctor_name"]: d for d in body["doctors"]}
    assert boards["Dr Queue"]["now_serving"] == 2
    assert boards["Dr Queue"]["waiting"] == 3
    assert "Dr Slot" not in boards  # token doctors only
    for n in range(1, 7):
        assert f"P{n}" not in r.text  # zero patient PII on a public board


async def test_display_unknown_branch_404_bad_uuid_400(db, client):
    # `db` is required even though unused: it patches backend.database to the
    # TEST engine. Without it this endpoint's get_db hit the REAL DATABASE_URL
    # (found 2026-07-05 when the sales-vertical columns made prod schema drift
    # from the model) — an integration test must never touch prod.
    r = await client.get(f"/queue/{uuid.uuid4()}/display")
    assert r.status_code == 404
    r = await client.get("/queue/not-a-uuid/display")
    assert r.status_code == 400


async def test_queue_position_found_with_ahead_count(clinic, db):
    res = await queue_position_by_phone(
        clinic["branch_uuid"], clinic["caller_phone"], db
    )
    assert res["found"] is True
    (entry,) = res["queue"]
    assert entry["doctor"] == "Dr Queue"
    assert entry["token_number"] == 5
    assert entry["now_serving"] == 2
    # token 4 is the only still-confirmed one below 5 (1-2 attended, 3 no_show)
    assert entry["patients_ahead"] == 1


async def test_queue_position_not_found_for_stranger(clinic, db):
    res = await queue_position_by_phone(clinic["branch_uuid"], "+919111222333", db)
    assert res["found"] is False


async def test_queue_position_branch_scoped(clinic, db):
    """RULE 1: same phone queried under another branch finds nothing."""
    res = await queue_position_by_phone(uuid.uuid4(), clinic["caller_phone"], db)
    assert res["found"] is False


async def test_queue_position_excludes_slot_doctor_booking(clinic, db):
    """A slot-doctor booking has no queue — the tool must not report it."""
    from datetime import time as time_cls

    slot_doc = (
        await db.execute(
            select(Doctor).where(
                Doctor.branch_id == clinic["branch_uuid"],
                Doctor.booking_type == "appointment",
            )
        )
    ).scalar_one()
    p = Patient(branch_id=clinic["branch_uuid"], name="Slot Patient",
                phone="+919666000099", is_primary=True)
    db.add(p)
    await db.flush()
    db.add(Token(branch_id=clinic["branch_uuid"], doctor_id=slot_doc.id,
                 patient_id=p.id, date=date.today(), token_number=None,
                 appointment_time=time_cls(16, 30), status="confirmed",
                 source="voice"))
    await db.commit()

    res = await queue_position_by_phone(clinic["branch_uuid"], "+919666000099", db)
    assert res["found"] is False
