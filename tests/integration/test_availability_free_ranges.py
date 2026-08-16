"""«When is the doctor available today?» means FREE time, not sitting hours.

Vinay 2026-08-03: "when i asked when will doctor available today it should say
all time together (like now time is 8. so it should say he is available from 8
to 9 - closing time). if there is one slot booked in between at 8:15. then it
should say (he is available from 8 to 8:15 and 8:30 to 9)."

Two things must hold, and both are easy to get wrong:
  * a booked slot splits the answer into SEVERAL ranges, all of them spoken in
    one reply — not just the first;
  * on today, time already gone is not availability.

The sitting hours are the wrong answer to this question, which is exactly what
get_doctor_schedule alone would have returned.
"""
import uuid
from datetime import date, datetime, time, timedelta

import pytest

from agent.tools.booking_tools import _merge_to_ranges, check_availability
from backend.services.doctor_schedule import bookable_starts_as_text
from backend.models.schema import Branch, Doctor, Organization, Patient, Token


def _ranges_text(slots, minutes):
    return " and ".join(
        f"{s.strftime('%I:%M %p').lstrip('0')} to {e.strftime('%I:%M %p').lstrip('0')}"
        for s, e in _merge_to_ranges(slots, minutes)
    )


def test_a_booking_at_815_splits_the_answer_into_two_ranges():
    """Vinay's exact example, on the pure slot arithmetic: 8-9 with 15-minute
    slots and 8:15 taken must read "8:00 to 8:15 and 8:30 to 9:00"."""
    free = [time(8, 0), time(8, 30), time(8, 45)]
    assert _ranges_text(free, 15) == "8:00 AM to 8:15 AM and 8:30 AM to 9:00 AM"


def test_an_unbroken_run_is_one_range_not_four():
    free = [time(20, 0), time(20, 15), time(20, 30), time(20, 45)]
    assert _ranges_text(free, 15) == "8:00 PM to 9:00 PM"


async def _clinic(db):
    org = Organization(
        name="FreeOrg", owner_phone="+919000700077",
        owner_email=f"free-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="FreeBranch", status="active",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
    )
    db.add(br)
    await db.commit()
    return org, br


@pytest.mark.asyncio
async def test_a_booked_slot_is_removed_from_the_spoken_availability(db, redis):
    """End to end: the one booked time disappears and the answer splits."""
    _org, br = await _clinic(db)
    tomorrow = date.today() + timedelta(days=1)
    doc = Doctor(
        branch_id=br.id, name="Dr Lakshmi", booking_type="appointment",
        slot_duration_minutes=15, max_concurrent_per_slot=1,
        schedule_mode="recurring",
        recurring_schedule={str(d): [{"start": "08:00", "end": "09:00"}] for d in range(7)},
    )
    db.add(doc)
    await db.flush()
    pat = Patient(branch_id=br.id, name="Booked Patient", phone="+919000012345")
    db.add(pat)
    await db.flush()
    db.add(Token(
        branch_id=br.id, doctor_id=doc.id, patient_id=pat.id, date=tomorrow,
        appointment_time=time(8, 15), source="voice", status="confirmed",
    ))
    await db.commit()

    answer = await check_availability(
        doctor_id=doc.id, branch_id=br.id, booking_date=tomorrow, db=db,
    )
    text = str(answer)
    assert "8:15 AM" not in text, "the booked start must not be offered"
    assert "8:00 AM" in text
    assert "8:30 AM to 8:45 AM" in text


def test_sitting_end_is_never_advertised_as_a_bookable_start():
    starts = [time(9), time(9, 30), time(10), time(10, 30), time(11), time(11, 30)]
    assert bookable_starts_as_text(starts, 30) == "9:00 AM to 11:30 AM"


@pytest.mark.asyncio
async def test_request_at_session_end_offers_nearest_without_claiming_occupied(db, redis):
    _org, br = await _clinic(db)
    tomorrow = date.today() + timedelta(days=1)
    doc = Doctor(
        branch_id=br.id,
        name="Dr Boundary",
        booking_type="appointment",
        slot_duration_minutes=30,
        max_concurrent_per_slot=1,
        schedule_mode="recurring",
        recurring_schedule={str(day): [{"start": "09:00", "end": "12:00"}] for day in range(7)},
    )
    db.add(doc)
    await db.commit()

    answer = await check_availability(
        doctor_id=doc.id,
        branch_id=br.id,
        booking_date=tomorrow,
        db=db,
        query_start=time(12),
        query_end=time(12),
    )

    assert "not a bookable appointment start" in answer
    assert "do NOT say it is already booked" in answer
    assert "NEAREST free times" in answer
    assert "11:30 AM" in answer


@pytest.mark.asyncio
async def test_today_never_offers_a_time_that_has_already_passed(db, redis):
    """At 8pm the morning is not availability — the reported bug was a 10 AM
    booking taken at 7:44pm."""
    _org, br = await _clinic(db)
    doc = Doctor(
        branch_id=br.id, name="Dr Past", booking_type="appointment",
        slot_duration_minutes=30, max_concurrent_per_slot=1,
        schedule_mode="recurring",
        recurring_schedule={str(d): [{"start": "00:15", "end": "23:45"}] for d in range(7)},
    )
    db.add(doc)
    await db.commit()

    answer = str(await check_availability(
        doctor_id=doc.id, branch_id=br.id, booking_date=date.today(), db=db,
    ))
    now = datetime.now().time()
    if now > time(1, 0):  # a run just after midnight has nothing behind it
        assert "12:15 AM" not in answer, "a passed slot must not be offered today"


@pytest.mark.asyncio
async def test_the_schedule_tool_hands_the_model_free_time_not_just_sittings(db):
    """get_doctor_schedule must carry free_now, or "when is he free" gets
    answered with the sitting block — booked slots and all."""
    import inspect

    from agent.livekit_minimal import agent as agent_mod
    from agent.prompts.grounded_prompt import build_grounded_prompt

    src = inspect.getsource(agent_mod)
    # Slice the WHOLE tool, bounded by the next @function_tool, not a fixed
    # byte count. The old [:4000] window silently excluded the tail of the
    # function: adding a 7-line log statement pushed `"free_now"` to offset
    # 4302 and failed this test without changing a line of its behaviour
    # (2026-08-12). A window that moves with unrelated edits tests the wrong
    # thing.
    tool = src[src.index("async def get_doctor_schedule"):]
    tool = tool.split("@function_tool", 1)[0]
    assert '"free_now"' in tool
    assert "check_availability(" in tool, "must reuse the slot arithmetic"

    prompt = build_grounded_prompt(
        clinic_name="C", doctors=[], emergency_contact="+919000000000",
        plan="clinic", language="en",
    )
    assert "free_now, NOT sitting_hours" in prompt
    assert "ALL\nthe free ranges in ONE answer" in prompt or \
           "ALL the free ranges in ONE answer" in prompt
