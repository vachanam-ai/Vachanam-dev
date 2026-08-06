"""LIVE end-to-end WhatsApp journey — real model, real tools, real database.

Run explicitly (it calls the Gemini API, costs money and is non-deterministic):

    E2E_LIVE=1 pytest tests/integration/test_e2e_live_journey.py -s

Skipped by default so CI stays deterministic. Everything is real except the two
things that would reach the outside world:
  - wa_service.send_text  -> captured instead of sent to Meta
  - Google Calendar       -> stubbed (RULE 4 keeps the write inside the booking,
                             so a booking cannot run without one)

The model, the tool loop, the Redis seat allocation, the duplicate guards and
every DB write are the production code paths.
"""
from __future__ import annotations

import os
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import select

from backend.models.schema import Branch, Doctor, Organization, Patient, Token
from backend.services import wa_agent, wa_booking, wa_service

pytestmark = pytest.mark.skipif(
    os.getenv("E2E_LIVE") != "1", reason="live E2E: set E2E_LIVE=1 to run"
)

CALLER = "919876500011"


class _Cal:
    async def create_booking_event(self, **kw) -> str:
        return f"evt-{uuid.uuid4().hex[:8]}"

    async def delete_event(self, *a, **kw) -> None:
        return None


class _Meta:
    async def send_template(self, *a, **kw):
        return True

    def __getattr__(self, _name):  # any send_* is a no-op
        async def _noop(*a, **kw):
            return True
        return _noop


@pytest.fixture
def captured(monkeypatch):
    """Replies the patient would have received, in order."""
    out: list[str] = []

    async def _send(branch, to, text, plan=None, **kw):
        out.append(text)
        return True

    monkeypatch.setattr(wa_service, "send_text", _send)
    # wa_enabled is a CONFIG gate (is a Meta token present on this machine),
    # not part of the conversation being tested. Prod has the token; this
    # laptop does not, and without this the handler returns before the model
    # ever runs.
    monkeypatch.setattr(wa_service, "wa_enabled", lambda branch, plan: True)
    monkeypatch.setattr(wa_agent.wa_service, "wa_enabled", lambda branch, plan: True)
    monkeypatch.setattr(wa_booking, "_LazyGoogleCalendar", _Cal)
    monkeypatch.setattr(wa_booking, "_default_meta_service", lambda: _Meta())
    return out


async def _clinic(db):
    org = Organization(
        name="E2E Clinic Org", owner_phone="+919000700099",
        owner_email=f"e2e-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="Sri Venkateshwara Clinic", status="active",
        timezone="Asia/Kolkata", address="12 Main Rd, Hyderabad",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
        wa_phone_number_id=f"pnid-{uuid.uuid4().hex[:6]}",
    )
    db.add(br)
    await db.commit()
    return org, br


async def _doctor(db, branch, name, spec):
    doc = Doctor(
        branch_id=branch.id, name=name, specialization=spec, status="active",
        booking_type="appointment", slot_duration_minutes=30,
        max_concurrent_per_slot=1, daily_token_limit=20,
        schedule_mode="recurring",
        recurring_schedule={str(d): [{"start": "09:00", "end": "13:00"}] for d in range(7)},
    )
    db.add(doc)
    await db.commit()
    return doc


def _tomorrow() -> str:
    return (date.today() + timedelta(days=1)).isoformat()


@pytest.mark.asyncio
async def test_full_patient_journey(db, redis, captured):
    _org, br = await _clinic(db)
    await _doctor(db, br, "Srinivas", "dental")
    await _doctor(db, br, "Lakshmi", "skin")

    async def say(text: str) -> str:
        await wa_agent.handle(db, br, "clinic", CALLER, text)
        reply = captured[-1] if captured else "(no reply)"
        print(f"\n  PATIENT> {text}\n  CLINIC > {reply}")
        return reply

    tmr = _tomorrow()
    print(f"\n{'=' * 72}\nLIVE WHATSAPP JOURNEY  (booking date = {tmr})\n{'=' * 72}")

    # 1. cold open
    r1 = await say("hi")
    assert r1 and r1 != wa_agent.FALLBACK_REPLY, "the model must answer a greeting"

    # 2. roster comes from the DB, not the prompt
    r2 = await say("what doctors do you have there?")
    assert "srinivas" in r2.lower() or "lakshmi" in r2.lower(), r2

    # 3. availability
    await say(f"is Srinivas free on {tmr} at 10am?")

    # 4. book — first-time patient, gives name + age
    await say("yes please book that. my name is Vinay, age 24")
    booked = (await db.execute(
        select(Token).join(Patient, Patient.id == Token.patient_id)
        .where(Token.status == "confirmed", Patient.name.ilike("%vinay%"))
    )).scalars().all()
    assert booked, "the self booking must exist in the database"
    print(f"\n  [DB] Vinay booked: {[str(t.appointment_time) for t in booked]}")

    # 5. family member on the SAME number (the loop Vinay hit on 08-04)
    await say(f"my father Narayana also needs to see Srinivas on {tmr} at 11am, he is 60")
    nara = (await db.execute(
        select(Token).join(Patient, Patient.id == Token.patient_id)
        .where(Token.status == "confirmed", Patient.name.ilike("%narayana%"))
    )).scalars().first()
    assert nara is not None, "the family booking must exist (no name loop)"
    print(f"\n  [DB] Narayana booked at {nara.appointment_time}")

    # 6. FIX #487 — moving the family member's booking must keep it HIS
    await say("actually please move my father's appointment to 11:30am")
    await db.commit()
    moved = (await db.execute(
        select(Token).join(Patient, Patient.id == Token.patient_id)
        .where(Token.status == "confirmed", Patient.name.ilike("%narayana%"))
    )).scalars().all()
    assert len(moved) == 1, f"exactly one live booking for Narayana, got {len(moved)}"
    owner = (await db.execute(
        select(Patient.name).where(Patient.id == moved[0].patient_id)
    )).scalar_one()
    assert "narayana" in owner.lower(), f"the move reassigned the booking to {owner}"
    print(f"\n  [DB] after move -> {owner} at {moved[0].appointment_time}")

    # Vinay's own booking must be untouched by his father's move
    still = (await db.execute(
        select(Token).join(Patient, Patient.id == Token.patient_id)
        .where(Token.status == "confirmed", Patient.name.ilike("%vinay%"))
    )).scalars().all()
    assert still, "the owner's own booking must survive the family member's move"

    # 7. FIX #488 — asking again must not be called a full slot
    r7 = await say("can you also book me with Srinivas at 12pm the same day?")
    assert "full" not in r7.lower(), f"must not claim the slot is full: {r7}"

    # 8. cancel
    await say("please cancel my own appointment")
    await db.commit()

    print(f"\n{'=' * 72}\nFINAL DATABASE STATE\n{'=' * 72}")
    rows = (await db.execute(
        select(Token, Patient.name).join(Patient, Patient.id == Token.patient_id)
        .where(Token.branch_id == br.id).order_by(Token.appointment_time)
    )).all()
    for t, nm in rows:
        print(f"  {nm:12s} {t.date} {t.appointment_time}  {t.status}")
    assert rows, "the journey must have written bookings"
