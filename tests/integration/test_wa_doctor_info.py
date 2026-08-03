"""WhatsApp must answer doctor questions from the DATABASE, like the phone does.

Vinay, 2026-08-03, after messaging the live clinic number:

    asked "dr.srinivas available" said "let me check with doctor and get
    back". also, this dr. srinivas available logged in dashboard.

    whatsapp should answer these. we are not selling some IVR kind of
    things. we are integrating AI for a reason. similar to calls, this
    should also fetch data from DB.

Root cause: `agent.prompts.whatsapp_prompt.INTENTS` had no availability
intent at all, so every "which doctors / when is Dr X free" question fell
through to `ask_doctor` — the branch that logs a ClinicQuestion and promises
a callback. The clinic already had the answer in its own records.

These tests pin the DB path end to end: the reply must name the doctor and
their real resolved hours, and must NOT create a ClinicQuestion.
"""
import uuid
from datetime import date, time, timedelta

import pytest
from sqlalchemy import select

from backend.models.schema import (
    Branch, ClinicQuestion, Doctor, DoctorUnavailability, Organization,
)
from backend.services import wa_chat


async def _clinic(db, *, plan="clinic"):
    org = Organization(
        name="DocInfoOrg", owner_phone="+919000700088",
        owner_email=f"docinfo-{uuid.uuid4().hex[:6]}@test.com",
        plan=plan, status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="DocInfo Clinic", status="active",
        timezone="Asia/Kolkata",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
        wa_phone_number_id="pnid-docinfo",
    )
    db.add(br)
    await db.commit()
    return org, br


async def _doctor(db, branch, name, sessions, *, booking_type="appointment"):
    """A doctor whose recurring week is `sessions` on EVERY weekday, so the
    test never depends on which day it runs."""
    doc = Doctor(
        branch_id=branch.id, name=name, specialization="general", status="active",
        booking_type=booking_type, slot_duration_minutes=15,
        max_concurrent_per_slot=1, daily_token_limit=20,
        schedule_mode="recurring",
        recurring_schedule={str(d): sessions for d in range(7)},
    )
    db.add(doc)
    await db.commit()
    return doc


# ── the reported bug ─────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_named_doctor_availability_is_answered_not_deferred(db):
    _org, br = await _clinic(db)
    await _doctor(db, br, "Srinivas", [{"start": "09:00", "end": "12:00"},
                                       {"start": "17:00", "end": "21:00"}])

    reply = await wa_chat._handle_doctor_info(
        db, br, "dr.srinivas available",
        doctor_name="srinivas", target_date=date.today() + timedelta(days=1),
    )

    assert "Srinivas" in reply
    assert "check that with the doctor" not in reply.lower()
    assert "09:00" in reply, reply


@pytest.mark.asyncio
async def test_asking_about_a_doctor_logs_no_clinic_question(db):
    """The dashboard filled up with "dr. srinivas available" rows the doctor
    then had to answer by hand. An availability question is not a question
    for the doctor."""
    _org, br = await _clinic(db)
    await _doctor(db, br, "Srinivas", [{"start": "09:00", "end": "12:00"}])

    await wa_chat._handle_doctor_info(
        db, br, "dr.srinivas available",
        doctor_name="srinivas", target_date=date.today() + timedelta(days=1),
    )

    rows = (
        await db.execute(select(ClinicQuestion).where(ClinicQuestion.branch_id == br.id))
    ).scalars().all()
    assert rows == []


@pytest.mark.asyncio
async def test_who_all_doctors_lists_the_roster(db):
    _org, br = await _clinic(db)
    await _doctor(db, br, "Srinivas", [{"start": "09:00", "end": "12:00"}])
    await _doctor(db, br, "Lakshmi", [{"start": "10:00", "end": "13:00"}])

    reply = await wa_chat._handle_doctor_info(
        db, br, "who all doctors available",
        doctor_name="", target_date=date.today() + timedelta(days=1),
    )

    assert "Srinivas" in reply and "Lakshmi" in reply


@pytest.mark.asyncio
async def test_a_removed_doctor_never_appears(db):
    """RULE: the roster is read live. Vinay removed Karishma and expected her
    gone everywhere, immediately."""
    _org, br = await _clinic(db)
    await _doctor(db, br, "Srinivas", [{"start": "09:00", "end": "12:00"}])
    gone = await _doctor(db, br, "Karishma", [{"start": "09:00", "end": "12:00"}])
    gone.status = "inactive"
    await db.commit()

    reply = await wa_chat._handle_doctor_info(
        db, br, "who all doctors", doctor_name="",
        target_date=date.today() + timedelta(days=1),
    )
    assert "Karishma" not in reply


@pytest.mark.asyncio
async def test_a_doctor_on_leave_is_reported_unavailable(db):
    _org, br = await _clinic(db)
    doc = await _doctor(db, br, "Srinivas", [{"start": "09:00", "end": "12:00"}])
    target = date.today() + timedelta(days=1)
    db.add(DoctorUnavailability(
        branch_id=br.id, doctor_id=doc.id, date=target, reason="on leave",
    ))
    await db.commit()

    reply = await wa_chat._handle_doctor_info(
        db, br, "is srinivas available tomorrow",
        doctor_name="srinivas", target_date=target,
    )
    assert "not available" in reply.lower()
    assert "09:00" not in reply


@pytest.mark.asyncio
async def test_an_unknown_doctor_gets_the_real_roster_back(db):
    _org, br = await _clinic(db)
    await _doctor(db, br, "Srinivas", [{"start": "09:00", "end": "12:00"}])

    reply = await wa_chat._handle_doctor_info(
        db, br, "is dr mehta there", doctor_name="mehta",
        target_date=date.today() + timedelta(days=1),
    )
    assert "couldn't find" in reply.lower()
    assert "Srinivas" in reply


@pytest.mark.asyncio
async def test_no_doctors_on_file_does_not_dead_end(db):
    _org, br = await _clinic(db)
    reply = await wa_chat._handle_doctor_info(
        db, br, "who all doctors", doctor_name="", target_date=date.today(),
    )
    assert reply == wa_chat._NO_DOCTORS_REPLY
    assert "call" not in reply.lower()  # banned escape hatch


# ── free ranges, not the first five slot times ───────────────────────────────

def test_contiguous_slots_merge_into_one_range():
    """Vinay: "now time is 8 ... it should say he is available from 8 to 9"
    — one sentence, not a list of slot times."""
    slots = [time(8, 0), time(8, 15), time(8, 30), time(8, 45)]
    assert wa_chat._merge_to_ranges(slots, 15) == [(time(8, 0), time(9, 0))]


def test_a_booked_slot_splits_the_range():
    """Vinay: "if there is one slot booked in between at 8:15 then it should
    say he is available from 8 to 8:15 and 8:30 to 9"."""
    slots = [time(8, 0), time(8, 30), time(8, 45)]
    assert wa_chat._merge_to_ranges(slots, 15) == [
        (time(8, 0), time(8, 15)),
        (time(8, 30), time(9, 0)),
    ]


def test_no_free_slots_merges_to_nothing():
    assert wa_chat._merge_to_ranges([], 15) == []


# ── name matching ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("asked", ["srinivas", "dr.srinivas", "Dr Srinivas",
                                   "srinivas garu", "doctor srinivas"])
def test_titles_and_punctuation_still_find_the_doctor(asked):
    assert wa_chat._name_matches("Srinivas Rao", asked)


def test_a_bare_title_does_not_match_every_doctor():
    """"doctor" alone must not resolve to whoever sorts first."""
    assert not wa_chat._name_matches("Srinivas Rao", "doctor")
    assert not wa_chat._name_matches("Srinivas Rao", "dr")


def test_a_different_doctor_does_not_match():
    assert not wa_chat._name_matches("Srinivas Rao", "lakshmi")
