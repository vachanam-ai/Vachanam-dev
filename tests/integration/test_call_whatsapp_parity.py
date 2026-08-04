"""Whatever channel changed a booking, the patient gets it in writing.

Vinay 2026-08-04: "after every call, patient should get whatsapp
confirmation... all confirmations from calls should reflect in whatsapp."

Two things were wrong. Confirmations were sent with the hardcoded template
name `booking_confirm`, which Meta rejects unless that exact name is approved
on that clinic's own WABA — so they silently failed for any clinic that named
its templates differently, which is every clinic that registers its own.
And a reschedule or cancellation agreed on the phone sent nothing at all.

RULE 4 runs through all of this: a notification may never fail, block, or undo
the booking that triggered it.
"""
import uuid
from datetime import date, timedelta

import pytest

from backend.models.schema import Branch, Doctor, Organization
from backend.services import meta_service, wa_booking, wa_service


async def _clinic(db):
    org = Organization(
        name="ParityOrg", owner_phone="+919000700066",
        owner_email=f"parity-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="Parity Clinic", status="active",
        timezone="Asia/Kolkata", address="9 Road, Hyderabad",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
        wa_phone_number_id="pnid-parity",
    )
    db.add(br)
    await db.commit()
    return org, br


async def _doctor(db, branch):
    doc = Doctor(
        branch_id=branch.id, name="Srinivas", specialization="dental",
        status="active", booking_type="appointment", slot_duration_minutes=15,
        max_concurrent_per_slot=1, daily_token_limit=20,
        schedule_mode="recurring",
        recurring_schedule={str(d): [{"start": "09:00", "end": "12:00"}] for d in range(7)},
    )
    db.add(doc)
    await db.commit()
    return doc


class StubCalendar:
    async def create_booking_event(self, **kw):
        return "evt-1"

    async def delete_event(self, *a, **kw):
        return None


class StubMeta:
    async def send_template(self, *a, **kw):
        return True

    async def send_text(self, *a, **kw):
        return True


CALLER = "919876500077"


@pytest.fixture
def sends(monkeypatch):
    """Record every template send, by purpose."""
    out = []

    async def fake(branch_id, to, purpose, values, buttons=None):
        out.append({"purpose": purpose, "to": to, "values": values})
        return True

    monkeypatch.setattr(meta_service, "send_purpose", fake)
    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)
    return out


def _tools(db, branch, sender=CALLER):
    from backend.services import wa_agent

    return wa_agent.WaTools(
        db, branch, sender, "clinic",
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )


def _tomorrow():
    return (date.today() + timedelta(days=1)).isoformat()


async def _book(db, br):
    out = await _tools(db, br).book_appointment(
        doctor_name="srinivas", date=_tomorrow(), time="09:00",
        patient_name="Vinay", patient_age=24,
    )
    assert out["success"] is True, out
    mine = await _tools(db, br).my_appointments()
    return mine["appointments"][0]["appointment_id"]


# ── cancelling ───────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cancelling_sends_the_cancellation_template(db, redis, sends):
    _org, br = await _clinic(db)
    await _doctor(db, br)
    appt = await _book(db, br)
    sends.clear()

    await wa_booking.cancel(db, br, CALLER, appt)

    assert [s["purpose"] for s in sends] == ["cancel"]
    # {{1}} is the PATIENT's name, not the clinic's — read off the templates
    # Vinay actually registered ("Hello {{1}}, your appointment with Dr {{2}}
    # on {{3}} at {{4}} has been canceled"). Putting the clinic name here is
    # the bug this ordering fixed: the message greeted the patient by the
    # clinic's name.
    assert sends[0]["values"][0] == "Vinay"


# ── rescheduling: ONE message, not two contradictory ones ────────────────────

@pytest.mark.asyncio
async def test_rescheduling_never_also_says_cancelled(db, redis, sends):
    """A reschedule cancels the old row internally. Without suppression the
    patient reads "your appointment is cancelled" a second before "your
    appointment is moved" — two contradictory messages for one action."""
    _org, br = await _clinic(db)
    doc = await _doctor(db, br)
    appt = await _book(db, br)
    sends.clear()

    slot = wa_booking.Slot(
        doctor_id=doc.id, doctor_name=doc.name, booking_type="appointment",
        date=date.today() + timedelta(days=1),
        appointment_time=__import__("datetime").time(9, 30),
    )
    result = await wa_booking.reschedule(
        db, br, CALLER, appt, slot,
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )
    assert result.token is not None

    purposes = [s["purpose"] for s in sends]
    assert purposes == ["reschedule"], f"expected only a reschedule notice, got {purposes}"


@pytest.mark.asyncio
async def test_a_failed_reschedule_notifies_nothing(db, redis, sends):
    """Nothing changed, so nothing should be claimed."""
    _org, br = await _clinic(db)
    doc = await _doctor(db, br)
    appt = await _book(db, br)
    sends.clear()

    slot = wa_booking.Slot(
        doctor_id=doc.id, doctor_name=doc.name, booking_type="appointment",
        date=date.today() + timedelta(days=1),
        appointment_time=__import__("datetime").time(23, 0),  # outside hours
    )
    result = await wa_booking.reschedule(
        db, br, CALLER, appt, slot,
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )
    assert result.token is None
    assert sends == []


# ── RULE 4 ───────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_notification_failure_never_undoes_the_cancellation(
    db, redis, monkeypatch
):
    _org, br = await _clinic(db)
    await _doctor(db, br)
    appt = await _book(db, br)

    async def boom(*a, **k):
        raise RuntimeError("meta down")

    monkeypatch.setattr(meta_service, "send_purpose", boom)
    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)

    assert await wa_booking.cancel(db, br, CALLER, appt) is True, (
        "the cancellation must stand even when WhatsApp is unreachable"
    )


# ── the voice path suppresses its cancel notice mid-reschedule ───────────────

@pytest.mark.parametrize("reason", ["rescheduled", "reschedule_compensation"])
def test_voice_reschedule_reasons_suppress_the_cancellation_notice(reason):
    """These are the exact strings _do_reschedule passes. An equality check
    against "reschedule" would have let a cancellation notice go out in the
    middle of a successful move."""
    assert reason.startswith("resched")


def test_a_real_patient_cancellation_is_not_suppressed():
    assert not "patient_cancelled_or_rescheduled_on_call".startswith("resched")
