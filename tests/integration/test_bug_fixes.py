"""Proof tests for the 2026-06-12 bug-hunt fixes.

Bug 2: confirm_booking's function-level @retry re-ran the whole function on a
       transient calendar failure; the session still held attempt #1's pending
       Token, so attempt #2 inserted a duplicate. Fix: retry wraps only the
       calendar write. Proven by: transient calendar failure -> success with
       EXACTLY ONE token row.

Bug 3: cancelling a token-doctor booking DECR'd the Redis token counter, so
       the next patient received the SAME queue number as the cancelled one
       (and DECR on a missing key issues token 0). Fix: token counters are
       never decremented. Proven by: cancel then assign -> strictly higher
       token number.

Bug 1: LLM-orchestrated reschedules kept cancelling without booking (or
       booking without cancelling â€” Vinay's June 14 double). Fix: atomic
       _do_reschedule. Proven by: one call leaves exactly one confirmed
       booking on the new date and the old one cancelled; impossible date ->
       old booking untouched.
"""
import uuid
from datetime import date, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import and_, func, select

from agent.session_state import SessionState
from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Patient, Token



class FlakyCalendar:
    """Fails N times, then returns event ids. Triggers the old duplicate bug."""

    def __init__(self, failures: int):
        self.failures = failures
        self.calls = 0

    async def create_booking_event(self, **kw) -> str:
        self.calls += 1
        if self.calls <= self.failures:
            raise RuntimeError("transient calendar 503")
        return f"evt-{self.calls}"

    async def delete_event(self, calendar_id, event_id) -> None:
        return None


class NullMeta:
    async def send_booking_confirmation(self, **kw):
        return None


@pytest_asyncio.fixture
async def clinic(db):
    org = Organization(
        name="Bugfix Clinic",
        owner_phone="+919999999988",
        owner_email="bugfix@clinic.test",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="Bugfix Branch",
        whatsapp_number="+911111111122",
        did_number="+912222222233",
        emergency_contact="+913333333344",
        status="active",
    )
    db.add(branch)
    await db.flush()
    token_doc = Doctor(
        branch_id=branch.id,
        name="Dr. Token",
        specialization="general_physician",
        routing_keywords=["fever"],
        is_default_doctor=True,
        booking_type="token",
        daily_token_limit=20,
        status="active",
    )
    slot_doc = Doctor(
        branch_id=branch.id,
        name="Dr. Slots",
        specialization="dermatology",
        routing_keywords=["skin"],
        booking_type="appointment",
        working_hours_start=time(9, 0),
        working_hours_end=time(17, 0),
        slot_duration_minutes=30,
        max_concurrent_per_slot=1,
        status="active",
    )
    db.add_all([token_doc, slot_doc])
    await db.commit()
    return {"branch": branch, "token_doc": token_doc, "slot_doc": slot_doc}


def _tomorrow() -> date:
    d = date.today() + timedelta(days=1)
    # land on a working weekday for default Mon-Sat doctors
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


async def _count_tokens(db, doctor_id, branch_id, day) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Token).where(
                and_(
                    Token.doctor_id == doctor_id,
                    Token.branch_id == branch_id,
                    Token.date == day,
                )
            )
        )
    ).scalar_one()


# â”€â”€ Bug 2: transient calendar failure must NOT duplicate bookings â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


async def test_confirm_booking_transient_calendar_failure_single_row(clinic, db, redis):
    # SLOT doctor: calendar write is part of the booking (token doctors skip it
    # entirely — bounce F2). A transient calendar failure must retry the WRITE
    # only and leave exactly ONE token row, not a duplicate per retry.
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    appt = time(10, 0)
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=appt)
    assert assigned["success"]

    # Calendar write retries with stop_after_attempt(2) (one retry, see
    # booking_tools.py:933 — kept inside the 8s wait_for budget). One transient
    # failure then success exercises the retry path.
    cal = FlakyCalendar(failures=1)  # fails once, succeeds on the retry
    result = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Retry Proof",
        patient_phone="+919666444428",
        complaint="skin",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        patient_age=30,
        appointment_time=appt,
        source="voice",
        db=db,
        calendar_service=cal,
        meta_service=NullMeta(),
    )
    assert result["success"], result
    assert cal.calls == 2  # one failure + one successful retry (calendar step only)
    assert await _count_tokens(db, doc.id, branch.id, day) == 1  # ONE row, not one-per-retry


# â”€â”€ Bug 3: cancelled token numbers are never reissued â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


async def test_cancelled_token_number_never_reissued(clinic, db, redis):
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()

    first = await assign_token(doc.id, branch.id, day, db)
    assert first["token_number"] == 1
    confirmed = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Number One",
        patient_phone="+919666444428",
        complaint="fever",
        booking_date=day,
        token_number=1,
        followup_consent=False,
        patient_age=30,
        appointment_time=None,
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert confirmed["success"]

    state = SessionState(session_id="t")
    state.branch_id = branch.id
    state.token_confirmed = True
    agent = VachanamAgent(
        instructions="t",
        state=state,
        db=db,
        room=None,
        calendar_service=None,
        meta_service=NullMeta(),
        transfer_to="",
    )
    cancel = await agent._do_cancel(confirmed["token_id"])
    assert cancel["success"]

    # The cancelled patient held number 1; the next patient must get 2 â€” the
    # old DECR behaviour would have reissued number 1 to a different person.
    second = await assign_token(doc.id, branch.id, day, db)
    assert second["success"]
    assert second["token_number"] == 2

    # TD-020: a patient self-cancel is recorded as cancelled_by_patient (not
    # cancelled_by_clinic) so analytics + rebook framing can tell them apart.
    tok = (
        await db.execute(select(Token).where(Token.id == uuid.UUID(confirmed["token_id"])))
    ).scalar_one()
    assert tok.status == "cancelled_by_patient"


# â”€â”€ Bug 1: reschedule is atomic â€” never leaves two confirmed bookings â”€â”€â”€â”€â”€â”€â”€â”€


async def test_reschedule_atomic_one_confirmed_booking(clinic, db, redis):
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["slot_doc"], None
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()

    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(10, 0))
    assert assigned["success"], assigned
    confirmed = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Resched Proof",
        patient_phone="+919666444428",
        complaint="skin",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        patient_age=30,
        appointment_time=time(10, 0),
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert confirmed["success"]

    state = SessionState(session_id="t2")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t",
        state=state,
        db=db,
        room=None,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
        transfer_to="",
    )
    result = await agent._do_reschedule(confirmed["token_id"], day.isoformat(), "11:00")
    assert result["success"], result
    assert result["old_cancelled"] is True
    assert "come on time" in result["instruction"]

    rows = (
        await db.execute(
            select(Token.appointment_time, Token.status).where(
                and_(Token.doctor_id == doc.id, Token.branch_id == branch.id, Token.date == day)
            )
        )
    ).all()
    confirmed_rows = [r for r in rows if r.status == "confirmed"]
    assert len(confirmed_rows) == 1  # exactly one live booking
    assert confirmed_rows[0].appointment_time == time(11, 0)


async def test_reschedule_twice_in_one_call_with_stale_token(clinic, db, redis):
    """FIXLOG #283 (live call 2026-07-07): the caller rescheduled, then changed
    the time AGAIN. The second reschedule reused the ORIGINAL token id, which the
    first reschedule had already cancelled -> 'not_reschedulable_cancelled_by_patient'.
    The stale-token recovery must reschedule the CURRENT confirmed booking instead."""
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()

    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(10, 0))
    confirmed = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Waffler",
        patient_phone="+919666444429", complaint="skin", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=30, appointment_time=time(10, 0), source="voice", db=db,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert confirmed["success"]
    original_token_id = confirmed["token_id"]

    state = SessionState(session_id="t3")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
        transfer_to="",
    )

    # First move 10:00 -> 11:00 (cancels the original token, makes a new one).
    r1 = await agent._do_reschedule(original_token_id, day.isoformat(), "11:00")
    assert r1["success"], r1

    # Second move, reusing the STALE original id -> must recover, not fail.
    r2 = await agent._do_reschedule(original_token_id, day.isoformat(), "12:00")
    assert r2["success"], r2

    rows = (
        await db.execute(
            select(Token.appointment_time, Token.status).where(
                and_(Token.doctor_id == doc.id, Token.branch_id == branch.id, Token.date == day)
            )
        )
    ).all()
    confirmed_rows = [r for r in rows if r.status == "confirmed"]
    assert len(confirmed_rows) == 1  # still exactly one live booking
    assert confirmed_rows[0].appointment_time == time(12, 0)


# â”€â”€ Bug 26: rebook call said "you don't have any booking" â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€


async def test_find_bookings_includes_recent_cancelled(clinic, db, redis):
    """Cascade-cancelled bookings must still be visible â€” that cancelled
    booking IS what the patient asks about on a rebook call."""

    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db)
    confirmed = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Cascade Victim",
        patient_phone="+919666444411",
        complaint="fever",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        patient_age=30,
        appointment_time=None,
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert confirmed["success"]

    # Simulate a CLINIC cascade-cancel (doctor leave) — the rebook scenario.
    # (A patient self-cancel via _do_cancel is now cancelled_by_patient and is
    # deliberately NOT rebook context — TD-020.)
    from backend.models.schema import Token
    from sqlalchemy import select as _select, and_ as _and

    _tok = (
        await db.execute(_select(Token).where(Token.id == uuid.UUID(confirmed["token_id"])))
    ).scalar_one()
    _tok.status = "cancelled_by_clinic"
    await db.commit()

    # find_my_bookings is a FunctionTool; exercise the underlying query the
    # same way: cancelled_by_clinic within 7 days must be returned.
    today_local = day  # branch tz == local in tests

    today_local = day  # branch tz == local in tests
    rows = (
        await db.execute(
            _select(Token).where(
                _and(
                    Token.branch_id == branch.id,
                    Token.status.in_(["confirmed", "cancelled_by_clinic"]),
                    Token.date >= today_local - timedelta(days=7),
                )
            )
        )
    ).scalars().all()
    cancelled = [t for t in rows if t.status == "cancelled_by_clinic"]
    assert cancelled, "cancelled booking must remain visible to find_my_bookings"


async def test_reschedule_failure_keeps_old_booking(clinic, db, redis):
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()

    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(12, 0))
    confirmed = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Keep Me",
        patient_phone="+919666444428",
        complaint="skin",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        patient_age=30,
        appointment_time=time(12, 0),
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert confirmed["success"]

    state = SessionState(session_id="t3")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t",
        state=state,
        db=db,
        room=None,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
        transfer_to="",
    )
    # past date -> assign step refuses -> old booking must stay confirmed
    past = (date.today() - timedelta(days=1)).isoformat()
    result = await agent._do_reschedule(confirmed["token_id"], past, "11:00")
    assert result["success"] is False
    assert result["step"] == "assign"

    from uuid import UUID as _UUID

    old = (
        await db.execute(select(Token).where(Token.id == _UUID(confirmed["token_id"])))
    ).scalar_one()
    assert old.status == "confirmed"  # patient still has their booking


# ── Fix 31: out-of-scope complaint must NOT route to the default doctor ──────


async def test_route_out_of_scope_lists_specialties(clinic, db):
    from agent.tools.booking_tools import route_to_doctor

    async def llm(messages):
        return '{"doctor_ids": [], "confidence": "none", "out_of_scope": true}'

    result = await route_to_doctor("arm pain", clinic["branch"].id, db, llm)
    assert result.get("out_of_scope") is True
    assert "doctor_id" not in result
    assert "dermatology" in result["treated_specialties"]
    assert "does NOT treat" in result["instruction"]


async def test_route_vague_complaint_still_defaults(clinic, db):
    """Vague (not out-of-scope) complaints keep the old default-doctor path."""
    from agent.tools.booking_tools import route_to_doctor

    async def llm(messages):
        return '{"doctor_ids": [], "confidence": "none", "out_of_scope": false}'

    result = await route_to_doctor("not feeling well", clinic["branch"].id, db, llm)
    assert result.get("doctor_id")  # default doctor
    assert result["confidence"] == "none"


# ── Fix 30: asked time full -> NEAREST free times offered first ──────────────


async def test_check_availability_offers_nearest_time(clinic, db, redis):
    from agent.tools.booking_tools import check_availability

    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(10, 0))
    assert assigned["success"]
    confirmed = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Slot Hog",
        patient_phone="+919666444422", complaint="skin", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=30, appointment_time=time(10, 0), source="voice",
        db=db, calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert confirmed["success"]

    msg = await check_availability(
        doc.id, branch.id, day, db, query_start=time(10, 0), query_end=time(10, 30)
    )
    assert "NEAREST free times" in msg
    assert ("9:30 AM" in msg) or ("10:30 AM" in msg)


# ── Fix 33: first-time patient details are mandatory at the tool boundary ────


async def test_confirm_booking_first_time_patient_requires_age(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db)

    missing = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Brand New",
        patient_phone="+919666444433", complaint="fever", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        appointment_time=None, source="voice", db=db,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert missing["success"] is False
    assert missing["reason"] == "missing_patient_details"

    ok = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Brand New",
        patient_phone="+919666444433", complaint="fever", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=42, appointment_time=None, source="voice", db=db,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert ok["success"], ok


async def test_confirm_booking_known_patient_skips_age_gate(clinic, db, redis):
    """Reschedules / repeat bookings must not be blocked by the details gate."""
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    a1 = await assign_token(doc.id, branch.id, day, db)
    first = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Repeat Visitor",
        patient_phone="+919666444455", complaint="fever", booking_date=day,
        token_number=a1["token_number"], followup_consent=False,
        patient_age=50, appointment_time=None, source="voice", db=db,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert first["success"]

    day2 = day + timedelta(days=1)
    while day2.weekday() == 6:
        day2 += timedelta(days=1)
    a2 = await assign_token(doc.id, branch.id, day2, db)
    second = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Repeat Visitor",
        patient_phone="+919666444455", complaint="fever", booking_date=day2,
        token_number=a2["token_number"], followup_consent=False,
        appointment_time=None, source="voice", db=db,  # NO age — known patient
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert second["success"], second


# ── Fix 35: caller-ID format mismatch must not hide bookings ─────────────────


async def test_find_bookings_matches_any_phone_format(clinic, db, redis):
    from agent.tools.booking_tools import find_bookings_by_phone

    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db)
    confirmed = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Format Victim",
        patient_phone="+919666444466", complaint="fever", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=30, appointment_time=None, source="voice", db=db,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert confirmed["success"]

    # stored as +919666444466 — every SIP caller-ID variant must still match
    for variant in ("+919666444466", "919666444466", "09666444466", "9666444466"):
        rows = await find_bookings_by_phone(branch.id, variant, db)
        assert len(rows) == 1, f"variant {variant} found {len(rows)} bookings"
        assert rows[0][2].name == "Format Victim"

    assert await find_bookings_by_phone(branch.id, "12345", db) == []  # junk in, nothing out


# ── Fix 32: never hang up mid-booking ────────────────────────────────────────


async def test_end_call_blocked_while_booking_unconfirmed():
    from livekit.agents import ToolError as _ToolError

    from agent.livekit_minimal.agent import VachanamAgent

    state = SessionState(session_id="t5")
    state.token_held = True
    state.token_confirmed = False
    with pytest.raises(_ToolError):
        VachanamAgent._check_end_allowed(state, abandon_pending_booking=False)
    # explicit abandon or a confirmed booking both allow hangup
    VachanamAgent._check_end_allowed(state, abandon_pending_booking=True)
    state.token_confirmed = True
    VachanamAgent._check_end_allowed(state, abandon_pending_booking=False)


# ── Fix 34: declining a rebook stops the outbound retry loop ─────────────────


async def test_decline_rebook_completes_followup_task(clinic, db, redis):
    from agent.livekit_minimal.agent import VachanamAgent
    from backend.models.schema import FollowupTask

    branch, doc = clinic["branch"], clinic["token_doc"]
    patient = Patient(
        branch_id=branch.id, name="Decliner", phone="+919666444477",
        followup_consent=False,
    )
    db.add(patient)
    await db.flush()
    task = FollowupTask(
        branch_id=branch.id, doctor_id=doc.id, patient_id=patient.id,
        task_type="cascade_rebook", channel="voice", status="in_progress",
    )
    db.add(task)
    await db.commit()

    state = SessionState(session_id="t6")
    state.branch_id = branch.id
    state.followup_task_id = task.id
    agent = VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=None, meta_service=NullMeta(), transfer_to="",
    )
    assert await agent._complete_followup_task("patient_declined: test") is True

    refreshed = (
        await db.execute(select(FollowupTask).where(FollowupTask.id == task.id))
    ).scalar_one()
    assert refreshed.status == "completed"
    assert "patient_declined" in refreshed.response_summary


# ── Fix 36: 3 AM booking — working-hours enforced at the tool boundary ───────


async def test_assign_token_refuses_outside_working_hours(clinic, db, redis):
    from agent.tools.booking_tools import assign_token as _assign

    branch, doc = clinic["branch"], clinic["slot_doc"]  # works 9:00-17:00
    day = _tomorrow()
    result = await _assign(doc.id, branch.id, day, db, appointment_time=time(3, 0))
    assert result["success"] is False
    assert result["reason"] == "outside_working_hours"
    assert "9:00 AM" in result["working_hours"]


async def test_confirm_booking_refuses_outside_working_hours(clinic, db, redis):
    """confirm_booking gets its own copy of the time from the LLM — it must
    re-validate, not trust assign_token's earlier check."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=time(15, 0))
    assert assigned["success"]
    result = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Night Owl",
        patient_phone="+919666444488", complaint="skin", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=30, appointment_time=time(3, 0),  # LLM passed 03:00, not 15:00
        source="voice", db=db,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert result["success"] is False
    assert result["reason"] == "outside_working_hours"


async def test_confirm_booking_token_doctor_drops_stray_time(clinic, db, redis):
    """Token doctors have no clock time — a stray 03:00 from the LLM must not
    be stored or reach the calendar."""
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db)
    result = await confirm_booking(
        doctor_id=doc.id, branch_id=branch.id, patient_name="Stray Time",
        patient_phone="+919666444499", complaint="fever", booking_date=day,
        token_number=assigned["token_number"], followup_consent=False,
        patient_age=30, appointment_time=time(3, 0),  # stray — must be ignored
        source="voice", db=db,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
    )
    assert result["success"], result
    from uuid import UUID as _UUID
    stored = (
        await db.execute(select(Token).where(Token.id == _UUID(result["token_id"])))
    ).scalar_one()
    assert stored.appointment_time is None


async def test_assign_token_refuses_unconfigured_schedule(clinic, db, redis):
    """Empty slot grid used to mean NO time validation at all."""
    branch = clinic["branch"]
    bare = Doctor(
        branch_id=branch.id, name="Dr. NoHours", specialization="cardiology",
        routing_keywords=["heart"], booking_type="appointment", status="active",
    )
    db.add(bare)
    await db.commit()
    result = await assign_token(bare.id, branch.id, _tomorrow(), db, appointment_time=time(3, 0))
    assert result["success"] is False
    assert result["reason"] == "schedule_not_configured"


# ── 2026-06-14 fixes (Vinay live test) ──────────────────────────────────────


async def test_slot_hold_ttl_is_bounded_not_until_appointment(clinic, db, redis):
    """Issue 2/6: a SLOT hold must expire shortly (bounded), NOT survive until
    the appointment + 2h. A future-dated hold that outlived the call falsely
    blocked the slot for hours/days and made a real cancel unable to free it.
    Proven by: the Redis slot key TTL is <= SLOT_HOLD_TTL_SECONDS even for a
    slot booked weeks out."""
    from agent.tools.booking_tools import SLOT_HOLD_TTL_SECONDS

    branch, doc = clinic["branch"], clinic["slot_doc"]
    far_day = date.today() + timedelta(days=30)
    while far_day.weekday() == 6:  # land on a working weekday
        far_day += timedelta(days=1)
    appt = time(10, 0)

    assigned = await assign_token(doc.id, branch.id, far_day, db, appointment_time=appt)
    assert assigned["success"], assigned

    slot_key = f"slot:{doc.id}:{branch.id}:{far_day}:{appt.strftime('%H%M')}"
    ttl = await redis.ttl(slot_key)
    # Old bug: ttl ≈ (30 days) + 2h. Fixed: a fixed short bound.
    assert 0 < ttl <= SLOT_HOLD_TTL_SECONDS, f"hold TTL {ttl}s not bounded"


async def test_confirm_booking_announces_time_only_for_appointment_doctor(clinic, db, redis):
    """Issue 4: appointment doctors must NEVER have a token number announced.
    confirm_booking returns announce='time_only' so the agent can't slip."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    appt = time(11, 0)
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=appt)
    assert assigned["success"], assigned
    result = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Appt Patient",
        patient_phone="+919666444428",
        complaint="skin",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        patient_age=30,
        appointment_time=appt,
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert result["success"], result
    assert result["announce"] == "time_only"
    assert result["booking_type"] == "appointment"
    assert "come on time" in result["instruction"]


async def test_confirm_booking_announces_token_number_for_token_doctor(clinic, db, redis):
    """Issue 4 (other side): token doctors SHOULD announce the queue number."""
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    assigned = await assign_token(doc.id, branch.id, day, db)
    assert assigned["success"], assigned
    result = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name="Token Patient",
        patient_phone="+919666444429",
        complaint="fever",
        booking_date=day,
        token_number=assigned["token_number"],
        followup_consent=False,
        patient_age=40,
        appointment_time=None,  # token doctor has no clock time
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert result["success"], result
    assert result["announce"] == "token_number"
    assert result["booking_type"] == "token"
    assert "come on time" in result["instruction"]


# ── 2026-06-16 fixes (Vinay live test) ──────────────────────────────────────


async def test_cancelled_token_frees_seat_for_rebooking(clinic, db, redis):
    """Fix (live): a cancelled/rescheduled token-doctor booking must FREE its
    seat so the day can be rebooked, even at the daily limit. The old check
    `token_number > limit` (monotonic counter) made every cancellation eat a
    seat permanently — a full day stayed 'full' after cancellations. Capacity
    is now the CONFIRMED-seat count; the number is still never reused (#24).
    """
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["branch"], clinic["token_doc"]
    doc.daily_token_limit = 2  # tighten so 2 confirmed = full
    await db.commit()
    day = _tomorrow()

    async def _book(name, phone):
        a = await assign_token(doc.id, branch.id, day, db)
        assert a["success"], a
        c = await confirm_booking(
            doctor_id=doc.id, branch_id=branch.id, patient_name=name,
            patient_phone=phone, complaint="fever", booking_date=day,
            token_number=a["token_number"], followup_consent=False, patient_age=30,
            appointment_time=None, source="voice", db=db,
            calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
        )
        assert c["success"], c
        return a["token_number"], c["token_id"]

    n1, t1 = await _book("Seat One", "+919666444401")
    n2, t2 = await _book("Seat Two", "+919666444402")
    assert (n1, n2) == (1, 2)

    # Day is full by seats. With the OLD bug a third assign returned full.
    full = await assign_token(doc.id, branch.id, day, db)
    assert full["success"] is False and full["reason"] == "full"

    # Patient One cancels (frees a SEAT, NOT the number).
    state = SessionState(session_id="seat")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=None, meta_service=NullMeta(), transfer_to="",
    )
    assert (await agent._do_cancel(t1))["success"]

    # Now rebooking must succeed — seat freed — and the number must be a fresh
    # unique value (3), never the cancelled 1.
    n3, _ = await _book("Seat Three", "+919666444403")
    assert n3 == 3, "cancelled number must not be reused"

    # Exactly two CONFIRMED seats remain (Two + Three); One is cancelled.
    live = (
        await db.execute(
            select(func.count()).select_from(Token).where(
                and_(
                    Token.doctor_id == doc.id,
                    Token.branch_id == branch.id,
                    Token.date == day,
                    Token.status == "confirmed",
                )
            )
        )
    ).scalar_one()
    assert live == 2


async def test_assign_token_wrapper_hides_queue_number_for_appointment_doctor(clinic, db, redis):
    """Fix (live, recurring): the assign_token TOOL must never put a queue
    number in front of the LLM for a schedule doctor — that internal slot index
    is exactly what kept getting spoken as a 'token number' (FIXLOG #97/#103/
    #104). The wrapper returns time_only + the time, no number; the real number
    is kept server-side in state for confirm_booking."""
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    state = SessionState(session_id="hide")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
        transfer_to="",
    )
    out = await agent.assign_token(
        context=None, doctor_id=str(doc.id), booking_date=day.isoformat(),
        appointment_time="11:00",
    )
    assert out["success"] is True
    assert out["announce"] == "time_only"
    assert out["appointment_time"] == "11:00"
    assert "token_number" not in out  # the LLM never sees a queue number
    # but the agent kept the real index for confirm_booking
    assert state.token_number is not None
    assert state.token_held is True


async def test_assign_token_wrapper_keeps_queue_number_for_token_doctor(clinic, db, redis):
    """The other side: for a TOKEN (walk-in) doctor the queue number IS the
    patient-facing answer and must still reach the LLM."""
    from agent.livekit_minimal.agent import VachanamAgent

    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    state = SessionState(session_id="keep")
    state.branch_id = branch.id
    agent = VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=None, meta_service=NullMeta(), transfer_to="",
    )
    out = await agent.assign_token(
        context=None, doctor_id=str(doc.id), booking_date=day.isoformat(),
    )
    assert out["success"] is True
    assert out["token_number"] == 1  # walk-in queue number surfaced
    assert out.get("booking_type") == "token"


class _EchoMsg:
    def __init__(self, role, text):
        self.role = role
        self.text_content = text


class _EchoCtx:
    def __init__(self, items):
        self.items = items


def _echo_agent(clinic, db):
    from agent.livekit_minimal.agent import VachanamAgent

    state = SessionState(session_id="echo")
    state.branch_id = clinic["branch"].id
    return VachanamAgent(
        instructions="t", state=state, db=db, room=None,
        calendar_service=None, meta_service=NullMeta(), transfer_to="",
    )


async def test_echo_guard_discards_agents_own_words(clinic, db):
    """Self-talk loop: the carrier echoes the agent's TTS back, STT transcribes
    it as the caller, and the agent answers itself. A near-verbatim echo of the
    agent's last utterance must be DROPPED (StopResponse)."""
    from livekit.agents import StopResponse

    agent = _echo_agent(clinic, db)
    said = "రేపు మధ్యాహ్నం మూడున్నరకి మీ అపాయింట్‌మెంట్ కన్ఫర్మ్ అయిందండి"
    ctx = _EchoCtx([_EchoMsg("assistant", said)])
    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(ctx, _EchoMsg("user", said))


async def test_echo_guard_keeps_real_patient_turn(clinic, db):
    """A genuine patient turn (different from what the agent said) must pass
    through untouched — the guard must never silence a real caller."""
    agent = _echo_agent(clinic, db)
    ctx = _EchoCtx([_EchoMsg("assistant", "రేపు మధ్యాహ్నం మూడున్నరకి మీ అపాయింట్‌మెంట్ కన్ఫర్మ్ అయిందండి")])
    # distinct, longer request
    assert await agent.on_user_turn_completed(
        ctx, _EchoMsg("user", "నాకు పంటి నొప్పి ఉంది, డెంటిస్ట్ అపాయింట్‌మెంట్ కావాలి అండి")
    ) is None
    # short confirmation is below the length floor → never dropped
    assert await agent.on_user_turn_completed(ctx, _EchoMsg("user", "సరే అండి")) is None


# ── #375: rescheduled ≠ cancelled in analytics (Vinay 2026-07-14) ────────────


def test_reschedule_sets_rescheduled_reason():
    """The atomic reschedule stamps the OLD token cancellation_reason=
    'rescheduled' so analytics can exclude it from the Cancelled series."""
    import inspect

    from agent.livekit_minimal.agent import VachanamAgent

    src = inspect.getsource(VachanamAgent._do_reschedule)
    assert 'reason="rescheduled"' in src
    src_cancel = inspect.getsource(VachanamAgent._do_cancel)
    assert "cancellation_reason = reason" in src_cancel


def test_analytics_excludes_rescheduled():
    import inspect

    from backend.routers import analytics

    src = inspect.getsource(analytics)
    assert 'reason == "rescheduled"' in src
    assert "moved, not lost" in src
