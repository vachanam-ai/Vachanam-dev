"""Doctor hours for a named day come from the DATABASE, per date.

Vinay 2026-08-03: "don't carry any dynamic things with prompt. doctor timings
can change. doctors may get replaced. anything can happen. so always depend on
DB for answering about doctors" and "'what about tomorrow' — it should handle
like tomorrow's date -> doctors availability tomorrow -> answer."

A clinic-wide prompt physically cannot hold per-date truth: published sessions,
leave and one-off overrides are per doctor per date. Before this tool the agent
had no way to fetch them, so a timing question either got an invented answer
("he is available from 9 to 6") or a dead end ("I don't know, I will send a
message to the clinic"). get_doctor_schedule resolves the date against the DB.
"""
import uuid
from datetime import date, time, timedelta

import pytest

from backend.models.schema import (
    Branch, Doctor, DoctorDateSchedule, DoctorUnavailability, Organization,
)
from backend.services.doctor_schedule import resolve_doctor_schedule, sessions_as_text


async def _clinic(db):
    org = Organization(
        name="SchedOrg", owner_phone="+919000700099",
        owner_email=f"sched-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="SchedBranch", status="active",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
    )
    db.add(br)
    await db.commit()
    return org, br


async def _doctor(db, br, **kw):
    d = Doctor(branch_id=br.id, name="Dr Srinivas", booking_type="token", **kw)
    db.add(d)
    await db.commit()
    return d


@pytest.mark.asyncio
async def test_split_shift_returns_both_sittings_for_that_date(db):
    """The reported bug: 9-12 and again 5-9 must never become one 9-to-6 span."""
    _org, br = await _clinic(db)
    tomorrow = date.today() + timedelta(days=1)
    doc = await _doctor(
        db, br,
        schedule_mode="recurring",
        recurring_schedule={
            str(day): [{"start": "09:00", "end": "12:00"},
                       {"start": "17:00", "end": "21:00"}]
            for day in range(7)
        },
    )

    schedule = await resolve_doctor_schedule(doc, br.id, tomorrow, db)
    hours = sessions_as_text(schedule.sessions)

    assert schedule.status == "available"
    assert len(schedule.sessions) == 2
    assert "9:00 AM to 12:00 PM" in hours
    assert "5:00 PM to 9:00 PM" in hours
    assert "9:00 AM to 6:00 PM" not in hours


@pytest.mark.asyncio
async def test_a_published_date_overrides_the_usual_week(db):
    """A doctor with no fixed week publishes each date; the answer must follow
    the published row, not any weekly pattern."""
    _org, br = await _clinic(db)
    target = date.today() + timedelta(days=2)
    doc = await _doctor(
        db, br, schedule_mode="date_specific",
        recurring_schedule={str(d): [{"start": "09:00", "end": "17:00"}] for d in range(7)},
    )
    db.add(DoctorDateSchedule(
        branch_id=br.id, doctor_id=doc.id, date=target,
        sessions=[{"start": "14:00", "end": "16:30"}],
    ))
    await db.commit()

    schedule = await resolve_doctor_schedule(doc, br.id, target, db)
    hours = sessions_as_text(schedule.sessions)
    assert schedule.source == "date_override"
    assert "2:00 PM to 4:30 PM" in hours
    assert "9:00" not in hours


@pytest.mark.asyncio
async def test_an_unpublished_date_is_unknown_never_invented(db):
    """Missing date-specific data is UNKNOWN. The tool must report that so the
    agent says so, instead of guessing hours or declaring the doctor off."""
    _org, br = await _clinic(db)
    doc = await _doctor(db, br, schedule_mode="date_specific")

    schedule = await resolve_doctor_schedule(
        doc, br.id, date.today() + timedelta(days=9), db
    )
    assert schedule.status == "unpublished"
    assert schedule.sessions == ()


@pytest.mark.asyncio
async def test_leave_beats_the_usual_week(db):
    _org, br = await _clinic(db)
    target = date.today() + timedelta(days=1)
    doc = await _doctor(
        db, br, schedule_mode="recurring",
        recurring_schedule={str(d): [{"start": "09:00", "end": "12:00"}] for d in range(7)},
    )
    db.add(DoctorUnavailability(
        branch_id=br.id, doctor_id=doc.id, date=target, reason="family function",
    ))
    await db.commit()

    schedule = await resolve_doctor_schedule(doc, br.id, target, db)
    assert schedule.status == "unavailable"
    assert schedule.source == "leave"


@pytest.mark.asyncio
async def test_a_timing_edit_is_reflected_on_the_very_next_lookup(db):
    """"doctor timings can change" — no cached copy may outlive the change."""
    _org, br = await _clinic(db)
    target = date.today() + timedelta(days=1)
    doc = await _doctor(
        db, br, schedule_mode="recurring",
        recurring_schedule={str(d): [{"start": "09:00", "end": "12:00"}] for d in range(7)},
    )
    before = await resolve_doctor_schedule(doc, br.id, target, db)
    assert "9:00 AM to 12:00 PM" in sessions_as_text(before.sessions)

    doc.recurring_schedule = {
        str(d): [{"start": "16:00", "end": "20:00"}] for d in range(7)
    }
    await db.commit()

    after = await resolve_doctor_schedule(doc, br.id, target, db)
    assert "4:00 PM to 8:00 PM" in sessions_as_text(after.sessions)
    assert "9:00 AM" not in sessions_as_text(after.sessions)


@pytest.mark.asyncio
async def test_the_tool_is_exposed_to_the_model_and_forbids_answering_from_memory(db):
    """A tool the model is never told to call is a tool that never runs."""
    import inspect

    from agent.livekit_minimal import agent as agent_mod
    from agent.prompts.grounded_prompt import build_grounded_prompt

    src = inspect.getsource(agent_mod)
    assert "async def get_doctor_schedule" in src
    tool = src[src.index("async def get_doctor_schedule"):]
    assert "resolve_doctor_schedule" in tool[:3000], "must read the DB"
    assert "unknown_doctor" in tool[:3000], "RULE 1: branch check"

    prompt = build_grounded_prompt(
        clinic_name="Test Clinic", doctors=[], emergency_contact="+919000000000",
        plan="clinic", language="en",
    )
    assert "get_doctor_schedule" in prompt
    assert "NEVER from the roster" in prompt
