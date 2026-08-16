"""WA MVP1 Task 7 — voice hard-blocked for the `wa` plan; manual (walk-in)
bookings send the WhatsApp confirmation that voice would have.

THE OVERRIDING CONSTRAINT: the four VOICE plans (lite/solo/clinic/multi) must
keep behaving through `call_blocked` EXACTLY as before this change — every
existing branch (paused, cancelled, trial_expired, minutes_exhausted, None).
`test_four_voice_plans_call_blocked_unchanged` is the proof: it re-runs every
assertion from `test_call_blocked_matrix`, `test_trial_always_hard_blocks_on_exhaust`,
and `test_trial_expiry_hard_stops_even_before_pause_job` in
tests/unit/test_billing_math.py against all four plans, not just `clinic`.
"""
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from backend.config import settings
from backend.models.schema import Branch, Doctor, Organization, Patient, Token
from backend.services import wa_service, wa_template_registry
from backend.services.billing_math import call_blocked

IST = ZoneInfo("Asia/Kolkata")

VOICE_PLANS = ("lite", "solo", "clinic", "multi")


# ── call_blocked: the "no_voice_plan" gate ───────────────────────────────────


def test_wa_plan_blocks_calls():
    """No DID and no minutes — a call reaching a `wa` org is a config error,
    not an overage."""
    assert call_blocked("active", "wa", True, 0) == "no_voice_plan"
    assert call_blocked("active", "wa", False, 0) == "no_voice_plan"


def test_four_voice_plans_call_blocked_unchanged():
    """Non-negotiable: the ONLY behavioural change permitted by this task is
    that a plan with no voice refuses. Every existing branch for every
    existing voice plan must still return exactly what it did before."""
    for plan in VOICE_PLANS:
        # paused / cancelled — win over everything else
        assert call_blocked("paused", plan, False, 0) == "paused"
        assert call_blocked("cancelled", plan, False, 0) == "cancelled"

        # hard block off -> overage allowed, never blocked (paying orgs)
        assert call_blocked("active", plan, False, 99999) is None

        # trial expiry (defense-in-depth ahead of the daily trial_pause job)
        now = datetime.now(timezone.utc)
        assert call_blocked(
            "trial", plan, False, 0, trial_ends_at=now + timedelta(hours=1)
        ) is None
        assert call_blocked(
            "trial", plan, False, 0, trial_ends_at=now - timedelta(minutes=1)
        ) == "trial_expired"
        # naive datetime from the DB is treated as UTC, still blocks
        assert call_blocked(
            "trial", plan, False, 0,
            trial_ends_at=(now - timedelta(days=2)).replace(tzinfo=None),
        ) == "trial_expired"

        # Trial usage is unlimited until the exact expiry, regardless of the
        # paid-plan hard-block flag or a minutes adjustment.
        assert call_blocked("trial", plan, False, 100_000) is None
        assert call_blocked("trial", plan, True, 100_000, adjustment=-100) is None

        # Usage-only current plans never cut off paid calls. Legacy Lite keeps
        # its historical bucket and hard-block behavior.
        included = {"lite": 150, "solo": 0, "clinic": 0, "multi": 0}[plan]
        assert call_blocked("active", plan, True, max(included - 1, 0)) is None
        expected = "minutes_exhausted" if included else None
        assert call_blocked("active", plan, True, max(included, 10_000)) == expected


def test_clinic_matrix_from_test_billing_math_still_holds():
    """Byte-for-byte the assertions in test_call_blocked_matrix (clinic plan)."""
    assert call_blocked("paused", "clinic", False, 0) == "paused"
    assert call_blocked("cancelled", "clinic", False, 0) == "cancelled"
    assert call_blocked("active", "clinic", False, 99999) is None
    assert call_blocked("active", "clinic", True, 1499) is None
    assert call_blocked("active", "clinic", True, 1500) is None


# ── pre_appt_reminder job: voice skipped, WhatsApp still fires ───────────────


@pytest.fixture
def wa_capture(monkeypatch):
    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)
    sent = []

    async def _fake(branch, to, template, lang, params, buttons=None, plan=None):
        sent.append({"template": template, "to": to, "params": params})
        return True

    monkeypatch.setattr(wa_service, "send_template", _fake)

    async def _resolve(branch, purpose):
        names = {
            "booking_confirm": "booking_confirm",
            "reminder": "appt_reminder",
        }
        params = {"booking_confirm": 5, "reminder": 4}
        return {
            "name": names[purpose], "language": "en", "params": params[purpose],
        } if purpose in names else None

    monkeypatch.setattr(wa_template_registry, "resolve", _resolve)
    return sent


async def _seed_in_window(db, plan: str, linked: bool = True):
    """A confirmed appointment-doctor token ~20 min out (inside the reminder
    window), reminder not yet sent, on an org of the given plan."""
    now = datetime.now(IST)
    appt = now + timedelta(minutes=20)
    org = Organization(
        id=uuid.uuid4(), name="WaJobOrg", owner_phone="+919000700099",
        owner_email=f"waj-{uuid.uuid4().hex[:6]}@test.com", plan=plan, status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        id=uuid.uuid4(), org_id=org.id, name="WaJobBranch",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", timezone="Asia/Kolkata",
        status="active",
        wa_phone_number_id=str(uuid.uuid4().int)[:12] if linked else None,
        wa_status="connected" if linked else "disconnected",
    )
    db.add(br)
    await db.flush()
    doc = Doctor(
        id=uuid.uuid4(), branch_id=br.id, name="Dr WaJob",
        booking_type="appointment", pre_appointment_reminder=True, status="active",
        slot_duration_minutes=15,
    )
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="WaJob Patient",
                  phone="+919000000199")
    db.add_all([doc, pat])
    await db.flush()
    tok = Token(
        id=uuid.uuid4(), branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
        token_number=1, date=appt.date(),
        appointment_time=appt.time().replace(microsecond=0),
        status="confirmed", reminder_sent=False, source="voice",
        # Booked yesterday — see the same note in
        # test_reminder_flip_after_dispatch: a default created_at makes this a
        # booking made 20 minutes before its own appointment, which gets no
        # reminder by design (booked_too_close). This test is about plan
        # gating, so the booking must be reminder-eligible in the first place.
        created_at=now - timedelta(days=1),
    )
    db.add(tok)
    await db.commit()
    return br, doc, pat, tok


@pytest.mark.asyncio
async def test_reminder_job_never_dials_a_wa_clinic(db, redis, monkeypatch, wa_capture):
    """The job gates on settings.voice_plane_configured — OUR platform, not the
    clinic's plan — so without the plan-level skip it would dial a clinic with
    no line at all."""
    monkeypatch.setenv("LIVEKIT_URL", "wss://x")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    from backend.jobs import pre_appt_reminder as job

    br, doc, pat, tok = await _seed_in_window(db, plan="wa")

    dispatched = []

    async def _spy(*a, **k):
        dispatched.append(1)
        return True

    monkeypatch.setattr(job, "_dispatch_reminder_call", _spy)

    await job.run_pre_appt_reminders()

    assert dispatched == []


@pytest.mark.asyncio
async def test_reminder_job_still_sends_the_wa_reminder(db, redis, monkeypatch, wa_capture):
    """Blocking the CALL must not block the WhatsApp reminder."""
    monkeypatch.setenv("LIVEKIT_URL", "wss://x")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    from backend.jobs import pre_appt_reminder as job
    from backend.services import wa_readiness

    async def _ready(*args, **kwargs):
        return {"reminder": True}

    monkeypatch.setattr(wa_readiness, "purpose_readiness", _ready)

    br, doc, pat, tok = await _seed_in_window(db, plan="wa")

    async def _never_called(*a, **k):
        raise AssertionError("voice must not be dialed for a wa-plan branch")

    monkeypatch.setattr(job, "_dispatch_reminder_call", _never_called)

    await job.run_pre_appt_reminders()

    assert any(s["template"] == "appt_reminder" for s in wa_capture)
    await db.refresh(tok)
    assert tok.reminder_sent is True  # not stuck retrying forever


@pytest.mark.asyncio
async def test_reminder_job_still_dials_voice_plans(db, redis, monkeypatch, wa_capture):
    """Regression guard: a normal voice-plan branch must still be dialed —
    only `wa` skips the call."""
    monkeypatch.setenv("LIVEKIT_URL", "wss://x")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    from backend.jobs import pre_appt_reminder as job

    br, doc, pat, tok = await _seed_in_window(db, plan="clinic")

    dispatched = []

    async def _spy(*a, **k):
        dispatched.append(1)
        return True

    monkeypatch.setattr(job, "_dispatch_reminder_call", _spy)

    await job.run_pre_appt_reminders()

    assert dispatched == [1]


# ── walk-in booking: WhatsApp confirmation ───────────────────────────────────


@pytest.fixture
async def client(redis):
    import httpx
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _owner_jwt(org_id: str, branch_id: str) -> str:
    import jwt

    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "owner@waplan.test", "role": "org_admin",
            "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm="HS256",
    )


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _wa_clinic(db):
    org = Organization(
        name="WaWalkinOrg", owner_phone="+919000700088",
        owner_email=f"waw-{uuid.uuid4().hex[:6]}@test.com", plan="wa", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="WaWalkinBranch",
        whatsapp_number=f"+9188{str(uuid.uuid4().int)[:8]}", status="active",
        wa_phone_number_id=str(uuid.uuid4().int)[:12],
        wa_status="connected",
    )
    db.add(branch)
    await db.commit()
    return org, branch


@pytest.mark.asyncio
async def test_walkin_booking_sends_whatsapp_confirmation(db, client, wa_capture):
    """For a WhatsApp-only clinic the receptionist IS a booking path — the
    patient must get the same written confirmation the voice path sends."""
    org, branch = await _wa_clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    dr = await client.post(
        f"/doctors/{branch.id}", headers=_auth(owner),
        json={"name": "Dr WaWalk", "specialization": "dentist",
              "routing_keywords": ["tooth"], "booking_type": "token",
              "daily_token_limit": 20,
              "working_hours_start": "00:00", "working_hours_end": "23:59",
              "available_weekdays": [0, 1, 2, 3, 4, 5, 6]},
    )
    assert dr.status_code in (200, 201), dr.text
    doctor_id = dr.json()["id"]

    r = await client.post(
        f"/queue/{branch.id}/walkin", headers=_auth(owner),
        json={"doctor_id": doctor_id, "patient_name": "Wa Walkin Patient",
              "patient_phone": "+919888800077"},
    )
    assert r.status_code == 201, r.text

    assert any(s["template"] == "booking_confirm" for s in wa_capture)


@pytest.mark.asyncio
async def test_walkin_booking_survives_a_whatsapp_failure(db, client, monkeypatch):
    """RULE 4 — a notification failure must never fail a booking."""
    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)
    monkeypatch.setattr(wa_service.settings, "meta_access_token", "tok", raising=False)

    async def _boom(*a, **k):
        raise RuntimeError("meta down")

    monkeypatch.setattr(wa_service, "send_template", _boom)

    org, branch = await _wa_clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    dr = await client.post(
        f"/doctors/{branch.id}", headers=_auth(owner),
        json={"name": "Dr WaWalk2", "specialization": "dentist",
              "routing_keywords": ["tooth"], "booking_type": "token",
              "daily_token_limit": 20,
              "working_hours_start": "00:00", "working_hours_end": "23:59",
              "available_weekdays": [0, 1, 2, 3, 4, 5, 6]},
    )
    assert dr.status_code in (200, 201), dr.text
    doctor_id = dr.json()["id"]

    r = await client.post(
        f"/queue/{branch.id}/walkin", headers=_auth(owner),
        json={"doctor_id": doctor_id, "patient_name": "Wa Walkin Failure",
              "patient_phone": "+919888800078"},
    )
    assert r.status_code == 201, r.text  # booking succeeds despite the WA failure


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
