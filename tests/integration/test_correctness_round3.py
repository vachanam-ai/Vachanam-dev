"""Regression proofs for bounty correctness round-3 fixes (B1..B25).

B1: a failed reschedule confirm left a flushed-but-uncommitted CONFIRMED Token
    in the live session; any later commit on the same session persisted a
    phantom booking. Fix: _do_reschedule rolls the session back on failure.
B2: confirm_booking never checked that appointment_time matches the held slot
    -> NULL-time bookings for slot doctors and a re-opened double-book race.
B4: state.token_confirmed never reset when a NEW hold was taken later in the
    same call -> RULE 3 release + cancel/end-call guards inert for booking #2.
"""
import uuid
from datetime import date, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import and_, func, select

from agent.session_state import SessionState
from agent.tools.booking_tools import assign_token, confirm_booking
from backend.models.schema import Branch, Doctor, Organization, Token

pytestmark = pytest.mark.asyncio


class FlakyCalendar:
    """Fails N times, then returns event ids."""

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
        name="CR3 Clinic",
        owner_phone="+919999999977",
        owner_email="cr3@clinic.test",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="CR3 Branch",
        whatsapp_number="+911111111133",
        did_number="+912222222244",
        emergency_contact="+913333333355",
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
    while d.weekday() == 6:  # land on a working weekday
        d += timedelta(days=1)
    return d


def _agent(clinic, db, state, calendar=None):
    from agent.livekit_minimal.agent import VachanamAgent

    return VachanamAgent(
        instructions="t",
        state=state,
        db=db,
        room=None,
        calendar_service=calendar or FlakyCalendar(failures=0),
        meta_service=NullMeta(),
        transfer_to="",
    )


async def _book_slot(clinic, db, day, appt, name="Old Booking", phone="+919666444428"):
    branch, doc = clinic["branch"], clinic["slot_doc"]
    assigned = await assign_token(doc.id, branch.id, day, db, appointment_time=appt)
    assert assigned["success"], assigned
    confirmed = await confirm_booking(
        doctor_id=doc.id,
        branch_id=branch.id,
        patient_name=name,
        patient_phone=phone,
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
    assert confirmed["success"], confirmed
    return confirmed


async def _confirmed_rows(db, doc_id, branch_id, day):
    return (
        await db.execute(
            select(Token.appointment_time, Token.status).where(
                and_(
                    Token.doctor_id == doc_id,
                    Token.branch_id == branch_id,
                    Token.date == day,
                    Token.status == "confirmed",
                )
            )
        )
    ).all()


# ── B1: failed reschedule must not leave a phantom pending Token ─────────────


async def test_b1_failed_reschedule_confirm_leaves_no_phantom_row(clinic, db, redis):
    """Calendar write fails during a reschedule confirm -> the flushed Token
    must be rolled back; a later commit on the SAME session (any other tool)
    must not persist a phantom confirmed booking."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    # Capture ids up-front: the reschedule rollback expires all ORM objects, so a
    # post-rollback attribute access would trigger a lazy reload (NullPool
    # checkout off-greenlet) — an artifact of the test session, not the fix.
    doc_id, branch_id = doc.id, branch.id
    day = _tomorrow()
    confirmed = await _book_slot(clinic, db, day, time(12, 0))

    state = SessionState(session_id="b1")
    state.branch_id = branch_id
    agent = _agent(clinic, db, state, calendar=FlakyCalendar(failures=2))

    result = await agent._do_reschedule(confirmed["token_id"], day.isoformat(), "11:00")
    assert result["success"] is False
    assert result["step"] == "confirm"

    # The failed confirm flushed a 'confirmed' 11:00 Token. Without the B1
    # rollback it stays pending in this live session and rides the NEXT tool's
    # commit — persisting a phantom booking with no calendar event. Simulate that
    # next tool: a fresh booking for a DIFFERENT patient at a DIFFERENT slot,
    # which commits on the same session. If the phantom row rode that commit we
    # would see THREE confirmed rows (original 12:00 + phantom 11:00 + new 14:00)
    # instead of TWO.
    a2 = await assign_token(doc_id, branch_id, day, db, appointment_time=time(14, 0))
    assert a2["success"] is True
    c2 = await confirm_booking(
        doctor_id=doc_id,
        branch_id=branch_id,
        patient_name="Next Caller",
        patient_phone="+919666440099",
        complaint="skin",
        booking_date=day,
        token_number=a2["token_number"],
        followup_consent=False,
        patient_age=25,
        appointment_time=time(14, 0),
        source="voice",
        db=db,
        calendar_service=FlakyCalendar(failures=0),
        meta_service=NullMeta(),
    )
    assert c2["success"] is True, c2

    import backend.database as _dbmod

    async with _dbmod.AsyncSessionLocal() as db2:
        n_confirmed = (
            await db2.execute(
                select(func.count()).select_from(Token).where(
                    and_(
                        Token.doctor_id == doc_id,
                        Token.branch_id == branch_id,
                        Token.date == day,
                        Token.status == "confirmed",
                    )
                )
            )
        ).scalar_one()
        n_at_11 = (
            await db2.execute(
                select(func.count()).select_from(Token).where(
                    and_(
                        Token.doctor_id == doc_id,
                        Token.branch_id == branch_id,
                        Token.date == day,
                        Token.appointment_time == time(11, 0),
                    )
                )
            )
        ).scalar_one()
    assert n_confirmed == 2, f"phantom booking rode a later commit: {n_confirmed} rows"
    assert n_at_11 == 0, "the failed 11:00 reschedule must leave NO row"


async def test_b1_retry_after_failed_reschedule_is_not_poisoned(clinic, db, redis):
    """After a failed reschedule, retrying the SAME reschedule must work and
    must not see the failed attempt's stray row as 'already_booked'."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    confirmed = await _book_slot(clinic, db, day, time(12, 0))

    state = SessionState(session_id="b1r")
    state.branch_id = branch.id
    flaky = FlakyCalendar(failures=2)  # both attempts of try #1 fail; try #2 works
    agent = _agent(clinic, db, state, calendar=flaky)

    first = await agent._do_reschedule(confirmed["token_id"], day.isoformat(), "11:00")
    assert first["success"] is False

    retry = await agent._do_reschedule(confirmed["token_id"], day.isoformat(), "11:00")
    assert retry["success"] is True, retry

    rows = await _confirmed_rows(db, doc.id, branch.id, day)
    assert len(rows) == 1
    assert rows[0].appointment_time == time(11, 0)


# ── B2: confirm time must match the held slot ────────────────────────────────


async def test_b2_confirm_without_time_uses_held_slot_not_null(clinic, db, redis):
    """LLM assigns 16:00 then confirms WITHOUT appointment_time: the booking
    must carry the held slot's time, never NULL (NULL-time slot bookings get
    no reminder, no real calendar time, no queue time)."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    state = SessionState(session_id="b2a")
    state.branch_id = branch.id
    state.patient_phone = "+919666444455"
    agent = _agent(clinic, db, state)

    out = await agent.assign_token(
        context=None, doctor_id=str(doc.id), booking_date=day.isoformat(),
        appointment_time="16:00",
    )
    assert out["success"] is True

    result = await agent.confirm_booking(
        context=None,
        doctor_id=str(doc.id),
        patient_name="Null Time",
        complaint="skin",
        booking_date=day.isoformat(),
        followup_consent=False,
        patient_age=30,
        appointment_time=None,  # LLM omitted it
    )
    assert result["success"] is True, result

    rows = await _confirmed_rows(db, doc.id, branch.id, day)
    assert len(rows) == 1
    assert rows[0].appointment_time == time(16, 0), (
        "confirm must inherit the HELD slot time, not write NULL"
    )


async def test_b2_confirm_with_different_time_regates_atomically(clinic, db, redis):
    """Hold 16:00, confirm 17:00 while ANOTHER caller's un-committed Redis hold
    occupies 17:00: the confirm must fail (atomic gate covers the confirmed
    time), not double-book past the DB re-count."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()

    # Another concurrent caller holds 17:00 (Redis only — no DB row yet).
    other_key = f"slot:{doc.id}:{branch.id}:{day}:1700"
    await redis.incr(other_key)

    state = SessionState(session_id="b2b")
    state.branch_id = branch.id
    state.patient_phone = "+919666444466"
    agent = _agent(clinic, db, state)

    out = await agent.assign_token(
        context=None, doctor_id=str(doc.id), booking_date=day.isoformat(),
        appointment_time="16:00",
    )
    assert out["success"] is True

    result = await agent.confirm_booking(
        context=None,
        doctor_id=str(doc.id),
        patient_name="Time Drift",
        complaint="skin",
        booking_date=day.isoformat(),
        followup_consent=False,
        patient_age=30,
        appointment_time="17:00",  # differs from the held 16:00
    )
    assert not result.get("success"), (
        f"confirm at a DIFFERENT time than the hold must re-gate atomically: {result}"
    )
    # the 16:00 hold was released when the time changed (RULE 3)
    assert int(await redis.get(f"slot:{doc.id}:{branch.id}:{day}:1600") or 0) == 0


async def test_b2_confirm_with_different_free_time_rebooks_cleanly(clinic, db, redis):
    """Hold 16:00, confirm 15:00 (free): booking lands at 15:00 with a real
    hold, and the stale 16:00 hold is released."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    day = _tomorrow()
    state = SessionState(session_id="b2c")
    state.branch_id = branch.id
    state.patient_phone = "+919666444477"
    agent = _agent(clinic, db, state)

    out = await agent.assign_token(
        context=None, doctor_id=str(doc.id), booking_date=day.isoformat(),
        appointment_time="16:00",
    )
    assert out["success"] is True

    result = await agent.confirm_booking(
        context=None,
        doctor_id=str(doc.id),
        patient_name="Moved Time",
        complaint="skin",
        booking_date=day.isoformat(),
        followup_consent=False,
        patient_age=30,
        appointment_time="15:00",
    )
    assert result["success"] is True, result
    rows = await _confirmed_rows(db, doc.id, branch.id, day)
    assert len(rows) == 1
    assert rows[0].appointment_time == time(15, 0)
    # stale 16:00 hold released; patient does not block a slot they left
    assert int(await redis.get(f"slot:{doc.id}:{branch.id}:{day}:1600") or 0) == 0


# ── B4: a NEW hold must clear token_confirmed ────────────────────────────────


async def test_b4_new_hold_resets_token_confirmed(clinic, db, redis):
    """After booking A confirms, taking a NEW hold for booking B (family
    booking) must reset token_confirmed so RULE 3 cleanup and the cancel/
    end-call guards protect booking B too."""
    branch, doc = clinic["branch"], clinic["token_doc"]
    day = _tomorrow()
    state = SessionState(session_id="b4")
    state.branch_id = branch.id
    state.token_confirmed = True  # booking A confirmed earlier in the call
    agent = _agent(clinic, db, state)

    out = await agent.assign_token(
        context=None, doctor_id=str(doc.id), booking_date=day.isoformat(),
    )
    assert out["success"] is True
    assert state.token_held is True
    assert state.token_confirmed is False, (
        "a fresh hold must clear the confirmed latch (RULE 3 + end-call guard)"
    )

    # and the end-call guard is live again for booking B
    from livekit.agents import ToolError as _ToolError

    from agent.livekit_minimal.agent import VachanamAgent

    with pytest.raises(_ToolError):
        VachanamAgent._check_end_allowed(state, abandon_pending_booking=False)


# ── B5: atomic seed-forward — evicted counter never re-issues a number ────────


async def test_b5_seed_forward_after_eviction_no_reuse(clinic, db, redis):
    """After a Redis eviction the counter reads 0 while N tokens are confirmed
    in the DB. The seed-forward must lift it to N+1 in ONE atomic step, and
    many concurrent assigns must all get distinct numbers (never a repeat)."""
    import asyncio

    import backend.database as _dbmod

    branch, doc = clinic["branch"], clinic["token_doc"]
    doc_id, branch_id = doc.id, branch.id
    day = _tomorrow()

    # Book 3 confirmed tokens, then simulate an eviction of the counter key.
    for i in range(3):
        a = await assign_token(doc_id, branch_id, day, db)
        c = await confirm_booking(
            doctor_id=doc_id, branch_id=branch_id, patient_name=f"Seed {i}",
            patient_phone=f"+91966644{i:04d}", complaint="fever", booking_date=day,
            token_number=a["token_number"], followup_consent=False, patient_age=30,
            appointment_time=None, source="voice", db=db,
            calendar_service=FlakyCalendar(failures=0), meta_service=NullMeta(),
        )
        assert c["success"]
    redis_key = f"token:{doc_id}:{branch_id}:{day}"
    await redis.delete(redis_key)  # eviction

    # Fire many concurrent assigns on independent sessions (gated so NullPool
    # never opens more connections than Postgres allows).
    sem = asyncio.Semaphore(5)

    async def _one():
        async with sem:
            async with _dbmod.AsyncSessionLocal() as s:
                return await assign_token(doc_id, branch_id, day, s)

    results = await asyncio.gather(*[_one() for _ in range(8)])
    numbers = [r["token_number"] for r in results if r.get("success")]
    assert len(numbers) == len(set(numbers)), f"duplicate token numbers: {numbers}"
    # every number is above the 3 already-confirmed seats (seed floor respected)
    assert min(numbers) >= 4, f"seed-forward re-issued a used number: {numbers}"
