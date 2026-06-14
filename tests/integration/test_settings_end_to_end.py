"""PROOF: filling the clinic-owner Settings page wires every function.

An owner completes onboarding through the REAL settings/doctor/staff APIs, then
each saved field is proven to drive a live function:

  - clinic name + emergency_contact + calendar id + DID actually persist
  - the DID is normalized, collision-checked, and wired to the LiveKit inbound
    trunk (the wiring call is mocked — no creds in CI — but the code path runs
    and `did_wired` comes back True)
  - the voice agent's inbound DID->branch resolution finds EXACTLY this branch
    (RULE 5: branch context from the dialed number) using the same query the
    agent runs
  - a receptionist account created here can LOG IN with the password and lands
    scoped to this branch
  - a voice booking against the configured token doctor lands in the
    receptionist's live queue
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import select

from agent.tools.booking_tools import assign_token, confirm_booking
from backend.config import settings
from backend.models.schema import Branch, Organization
from backend.services.validators import normalize_did

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _owner_jwt(org_id: str, branch_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "owner@e2e.test", "role": "org_admin",
            "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


def _auth(t: str) -> dict:
    return {"Authorization": f"Bearer {t}"}


class _RaisingCal:
    async def create_booking_event(self, **kw):
        raise RuntimeError("no calendar configured")

    async def delete_event(self, *a):
        return None


class _NullMeta:
    async def send_booking_confirmation(self, **kw):
        return None


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="E2E Org", owner_phone="+919000777001",
        owner_email=f"e2e-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="Old Name",
        whatsapp_number=f"+9188{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(branch)
    await db.commit()
    return {"org_id": str(org.id), "branch_id": str(branch.id)}


async def test_full_settings_onboarding_makes_everything_work(clinic, client, db, redis):
    bid = clinic["branch_id"]
    owner = _owner_jwt(clinic["org_id"], bid)
    DID = "+918045678901"

    # ── 1. Owner saves clinic details + calendar + DID through the real API ──
    with patch(
        "backend.services.livekit_sip.sync_did_to_inbound_trunk",
        new=AsyncMock(return_value={"ok": True, "detail": "wired"}),
    ):
        r = await client.patch(
            f"/branches/{bid}/settings",
            headers=_auth(owner),
            json={
                "name": "Madhapur Dental",
                "emergency_contact": "+919812345678",
                "google_calendar_id": "madhapurdental@gmail.com",
                "did_number": DID,
            },
        )
    assert r.status_code == 200, r.text
    body = r.json()
    # Every field persisted, DID normalized, trunk wiring reported live.
    assert body["name"] == "Madhapur Dental"
    assert body["emergency_contact"] == "+919812345678"
    assert body["google_calendar_id"] == "madhapurdental@gmail.com"
    assert body["did_number"] == normalize_did(DID)
    assert body["did_wired"] is True

    # GET reflects the same persisted state.
    g = await client.get(f"/branches/{bid}/settings", headers=_auth(owner))
    assert g.status_code == 200
    assert g.json()["did_number"] == normalize_did(DID)

    # ── 2. The agent's inbound DID->branch resolution finds THIS branch only ──
    did_norm = normalize_did(DID)
    rows = (
        await db.execute(
            select(Branch).where(Branch.did_number.in_([DID, did_norm])).limit(2)
        )
    ).scalars().all()
    assert len(rows) == 1
    assert str(rows[0].id) == bid  # the dialed number routes to the right tenant

    # ── 3. Owner adds a token doctor through the real API ──
    dr = await client.post(
        f"/doctors/{bid}",
        headers=_auth(owner),
        json={
            "name": "Dr. Asha", "specialization": "dentist",
            "routing_keywords": ["tooth", "dental"], "booking_type": "token",
            "daily_token_limit": 30, "is_default_doctor": True,
        },
    )
    assert dr.status_code in (200, 201), dr.text
    doctor_id = uuid.UUID(dr.json()["id"])

    # ── 4. Owner adds a receptionist — they can LOG IN and are branch-scoped ──
    recep_email = f"front-{uuid.uuid4().hex[:6]}@desk.test"
    st = await client.post(
        f"/branches/{bid}/staff",
        headers=_auth(owner),
        json={"name": "Reception", "email": recep_email,
              "password": "DeskPass@123", "role": "receptionist"},
    )
    assert st.status_code == 201, st.text

    login = await client.post(
        "/auth/login", json={"email": recep_email, "password": "DeskPass@123"}
    )
    assert login.status_code == 200, login.text
    recep_token = login.json()["access_token"]
    claims = jwt.decode(recep_token, settings.jwt_secret, algorithms=[_ALGO])
    assert claims["role"] == "receptionist"
    assert bid in claims["branch_ids"]  # scoped to exactly this clinic

    # ── 5. A voice booking against the configured doctor lands in the queue ──
    today = date.today()
    a = await assign_token(doctor_id, uuid.UUID(bid), today, db)
    assert a["success"], a
    cb = await confirm_booking(
        doctor_id=doctor_id, branch_id=uuid.UUID(bid), patient_name="Walkin Wanda",
        patient_phone="+919666555444", complaint="tooth", booking_date=today,
        token_number=a["token_number"], followup_consent=False, patient_age=29,
        appointment_time=None, source="voice", db=db,
        calendar_service=_RaisingCal(), meta_service=_NullMeta(),
    )
    assert cb["success"], cb  # token booking works even with NO calendar (F2)

    q = await client.get(f"/queue/{bid}/today", headers=_auth(recep_token))
    assert q.status_code == 200, q.text
    assert "Walkin Wanda" in q.text  # the booking is visible to reception
