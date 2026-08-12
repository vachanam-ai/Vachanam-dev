"""A reminder read to an answering machine was never delivered — retry it.

Vinay 2026-08-13: "calls going to voicemail are getting missed. because, as
call hits voice mail, the agent assumes patient answered call and it is
speaking. now, no reply will come from other end and call is marked completed."

Exactly right, and the mechanism is in pre_appt_reminder.py:

    ok = await _dispatch_reminder_call(branch, token, doctor, patient)
    if ok:
        token.reminder_sent = True

`ok` means the LiveKit dispatch was CREATED. A machine answers, so
`wait_until_answered` returns, the dispatch succeeds, `ok` is True, and the
booking is marked reminded forever. The patient never heard it.

The fix reuses the existing bounded dial-fail retry rather than inventing a
second path — that function already re-checks the booking is confirmed and
in-window, counts against _REMINDER_MAX_DIAL_ATTEMPTS, and clears the wake
gate. This file proves the new TRIGGER; the retry mechanics themselves are
covered by test_reminder_flip_after_dispatch.py.
"""
from __future__ import annotations

import uuid
from datetime import datetime, time, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from agent.livekit_minimal.agent import (
    _REMINDER_MAX_DIAL_ATTEMPTS,
    _reminder_retry_on_dial_fail,
    _reminder_went_unheard,
)
from backend.models.schema import Branch, Doctor, Organization, Patient, Token


# ── the decision itself ───────────────────────────────────────────────────

def test_a_reminder_nobody_spoke_on_is_unheard():
    assert _reminder_went_unheard(True, 0) is True


def test_a_reminder_the_patient_answered_is_left_alone():
    assert _reminder_went_unheard(True, 1) is False
    assert _reminder_went_unheard(True, 7) is False


def test_an_unknown_turn_count_never_redials():
    """-1 is the sentinel for "the call-quality write threw before counting".

    Re-dialling on unknown would call a patient who may well have answered.
    """
    assert _reminder_went_unheard(True, -1) is False


def test_an_inbound_or_non_reminder_call_is_never_retried():
    """A patient who calls in and says nothing must not trigger an outbound."""
    assert _reminder_went_unheard(False, 0) is False
    assert _reminder_went_unheard(False, -1) is False


# ── end to end against the database ───────────────────────────────────────

async def _booking(db: AsyncSession, *, minutes_ahead: int = 20) -> tuple[Token, dict]:
    org = Organization(
        id=uuid.uuid4(), name="C", plan="clinic", status="active",
        owner_phone=f"+9198{uuid.uuid4().int % 100000000:08d}",
        owner_email=f"{uuid.uuid4().hex[:10]}@example.com",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        id=uuid.uuid4(), org_id=org.id, name="Main", timezone="Asia/Kolkata",
        address="A", whatsapp_number=f"+9198{uuid.uuid4().int % 100000000:08d}",
    )
    db.add(branch)
    await db.flush()
    doctor = Doctor(
        id=uuid.uuid4(), branch_id=branch.id, name="Srinivas",
        specialization="Dental", status="active", booking_type="appointment",
        working_hours_start=time(0, 0), working_hours_end=time(23, 59),
        available_weekdays=[0, 1, 2, 3, 4, 5, 6],
    )
    db.add(doctor)
    await db.flush()
    patient = Patient(
        id=uuid.uuid4(), branch_id=branch.id, name="Vinay",
        phone=f"+9199{uuid.uuid4().int % 100000000:08d}",
    )
    db.add(patient)
    await db.flush()

    from zoneinfo import ZoneInfo

    local_now = datetime.now(ZoneInfo("Asia/Kolkata"))
    appt = local_now + timedelta(minutes=minutes_ahead)
    token = Token(
        id=uuid.uuid4(), branch_id=branch.id, doctor_id=doctor.id,
        patient_id=patient.id, date=appt.date(), token_number=1,
        appointment_time=appt.time().replace(second=0, microsecond=0),
        status="confirmed", source="voice", reminder_sent=True,
    )
    db.add(token)
    await db.commit()
    meta = {
        "call_type": "reminder",
        "token_id": str(token.id),
        "branch_id": str(branch.id),
    }
    return token, meta


@pytest.mark.asyncio
async def test_voicemail_reopens_the_reminder_for_another_attempt(db: AsyncSession, redis):
    """The bug, end to end: reminder_sent goes back to False so a tick re-dials."""
    token, meta = await _booking(db)
    assert token.reminder_sent is True  # what the voicemail call left behind

    assert _reminder_went_unheard(True, 0) is True
    await _reminder_retry_on_dial_fail(meta)

    await db.refresh(token)
    assert token.reminder_sent is False, "voicemail left the reminder marked delivered"
    assert token.reminder_30m_dial_attempts == 1


@pytest.mark.asyncio
async def test_retrying_stops_at_the_attempt_ceiling(db: AsyncSession, redis):
    """A phone that always goes to voicemail must not be dialled forever."""
    token, meta = await _booking(db)

    for _ in range(_REMINDER_MAX_DIAL_ATTEMPTS + 2):
        await db.refresh(token)
        token.reminder_sent = True
        await db.commit()
        await _reminder_retry_on_dial_fail(meta)

    await db.refresh(token)
    assert token.reminder_30m_dial_attempts > _REMINDER_MAX_DIAL_ATTEMPTS
    assert token.reminder_sent is True, "kept re-dialling past the ceiling"


@pytest.mark.asyncio
async def test_a_cancelled_booking_is_never_redialled(db: AsyncSession, redis):
    """Voicemail on a booking cancelled meanwhile must not resurrect the call."""
    token, meta = await _booking(db)
    token.status = "cancelled_by_patient"
    await db.commit()

    await _reminder_retry_on_dial_fail(meta)

    await db.refresh(token)
    assert token.reminder_sent is True, "re-opened a reminder for a cancelled booking"


@pytest.mark.asyncio
async def test_the_agent_calls_the_predicate_at_teardown(db: AsyncSession):
    """The predicate is only worth anything if the shutdown path consults it."""
    from pathlib import Path

    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    assert "_reminder_went_unheard(is_reminder, _patient_turns_seen)" in src
    assert "_patient_turns_seen = -1" in src, "no safe default before the count"
    assert "_patient_turns_seen = turns" in src, "the real count is never captured"
    # The retry must be the existing bounded one, not a fresh dial.
    teardown = src.split(
        "_reminder_went_unheard(is_reminder, _patient_turns_seen)", 1
    )[1][:400]
    assert "_reminder_retry_on_dial_fail(meta)" in teardown
