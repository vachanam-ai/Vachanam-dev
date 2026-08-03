"""WA MVP1 Task 5: chat booking — slots -> atomic token -> calendar -> confirm.

Highest-risk module in the WhatsApp MVP1 plan: it touches money (Redis token
allocation) and double-booking. Every test here proves one of:

  RULE 2 — assign_token (the SAME atomic Redis INCR the voice path uses) is
           the only place a token is ever allocated.
  Section 7.1 — offer_slots() never reserves anything; the token is taken
           only inside confirm().
  RULE 4 — the calendar write is part of the booking (failure rolls back the
           token AND the DB insert); a WhatsApp send failure never fails a
           booking.
  RULE 1 — every query is branch-scoped.

Same harness convention as tests/integration/test_confirm_booking_pref_lang.py
and tests/integration/test_bug_fixes.py (StubCalendar/StubMeta, recurring
schedule shape, `_tomorrow()` weekday guard).
"""
from __future__ import annotations

import uuid
from datetime import date, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import and_, func, select

from backend.models.schema import Branch, Doctor, Organization, Patient, Token
from backend.services import wa_booking
from backend.services.wa_booking import BookingFailed, Slot

pytestmark = pytest.mark.asyncio


class StubCalendar:
    def __init__(self, *, raise_error: bool = False):
        self.raise_error = raise_error
        self.calls = 0

    async def create_booking_event(self, **kw) -> str:
        self.calls += 1
        if self.raise_error:
            raise RuntimeError("calendar down")
        return f"evt-{self.calls}"

    async def delete_event(self, calendar_id, event_id) -> None:
        return None


class StubMeta:
    def __init__(self, *, raise_error: bool = False):
        self.raise_error = raise_error
        self.sent: list[dict] = []

    async def send_booking_confirmation(self, **kw):
        if self.raise_error:
            raise RuntimeError("meta down")
        self.sent.append(kw)


def _tomorrow() -> date:
    d = date.today() + timedelta(days=1)
    while d.weekday() == 6:
        d += timedelta(days=1)
    return d


@pytest_asyncio.fixture
async def clinic(db):
    """One org/branch with a token doctor (open all week) and a slot doctor
    (09:00-17:00, 30-min slots, 1 concurrent) — mirrors test_bug_fixes.py's
    `clinic` fixture so booking_tools behaves identically for both."""
    org = Organization(
        name="WaBooking Org", owner_phone="+919000900001",
        owner_email=f"wabooking-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="WaBooking Branch", whatsapp_number="+911100000099",
        clinic_phone="+914012340099", status="active",
    )
    db.add(branch)
    await db.flush()
    token_doc = Doctor(
        branch_id=branch.id, name="Dr. Token", specialization="general_physician",
        routing_keywords=["fever"], is_default_doctor=True, booking_type="token",
        schedule_mode="recurring",
        recurring_schedule={str(i): [{"start": "00:00", "end": "23:59"}] for i in range(7)},
        daily_token_limit=20, status="active",
    )
    slot_doc = Doctor(
        branch_id=branch.id, name="Dr. Slots", specialization="dermatology",
        routing_keywords=["skin"], booking_type="appointment",
        schedule_mode="recurring",
        recurring_schedule={
            str(i): [{"start": "09:00", "end": "17:00"}] for i in range(7)
        },
        slot_duration_minutes=30, max_concurrent_per_slot=1, status="active",
    )
    db.add_all([token_doc, slot_doc])
    await db.commit()
    return {"org": org, "branch": branch, "token_doc": token_doc, "slot_doc": slot_doc}


async def _token_count(db, branch) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Token).where(Token.branch_id == branch.id)
        )
    ).scalar_one()


async def _confirmed_count(db, branch, doctor) -> int:
    return (
        await db.execute(
            select(func.count()).select_from(Token).where(
                and_(
                    Token.branch_id == branch.id,
                    Token.doctor_id == doctor.id,
                    Token.status == "confirmed",
                )
            )
        )
    ).scalar_one()


def _token_slot(doc) -> Slot:
    return Slot(
        doctor_id=doc.id, doctor_name=doc.name, booking_type="token",
        date=_tomorrow(), appointment_time=None,
        patient_name="Ravi Kumar", patient_age=30,
    )


def _slot_at(doc, when: time) -> Slot:
    return Slot(
        doctor_id=doc.id, doctor_name=doc.name, booking_type="appointment",
        date=_tomorrow(), appointment_time=when,
        patient_name="Meena", patient_age=28,
    )


# ── RULE 2 — atomic token assignment ─────────────────────────────────────────


async def test_chat_booking_assigns_an_atomic_token(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["token_doc"]
    slot = _token_slot(doc)

    r = await wa_booking.confirm(
        db, branch, "919000000001", slot,
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )

    assert r.token is not None, r
    assert r.token.token_number >= 1
    assert r.token.status == "confirmed"


async def test_second_booking_gets_the_next_sequential_token(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["token_doc"]

    r1 = await wa_booking.confirm(
        db, branch, "919000000001", _token_slot(doc),
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )
    r2 = await wa_booking.confirm(
        db, branch, "919000000002",
        Slot(doctor_id=doc.id, doctor_name=doc.name, booking_type="token",
             date=_tomorrow(), patient_name="Second Patient", patient_age=40),
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )

    assert r1.token is not None and r2.token is not None
    assert r2.token.token_number == r1.token.token_number + 1


# ── Section 7.1 — no reservation before confirmation ─────────────────────────


async def test_no_hold_is_taken_before_confirmation(clinic, db, redis):
    """offer_slots() must be pure read: it never calls assign_token, so the
    Redis counter and the confirmed-token count are both untouched."""
    branch, doc = clinic["branch"], clinic["token_doc"]
    before = await _confirmed_count(db, branch, doc)
    redis_key = f"token:{doc.id}:{branch.id}:{_tomorrow()}"

    slots = await wa_booking.offer_slots(
        db, branch, "tomorrow morning", doctor_id=doc.id, booking_date=_tomorrow(),
    )

    assert slots, "expected at least one offered slot"
    assert await _confirmed_count(db, branch, doc) == before
    assert await redis.get(redis_key) is None


async def test_offer_slots_appointment_doctor_returns_open_times(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["slot_doc"]

    slots = await wa_booking.offer_slots(
        db, branch, "tomorrow morning", doctor_id=doc.id, booking_date=_tomorrow(),
    )

    assert slots
    assert all(s.booking_type == "appointment" for s in slots)
    assert all(s.appointment_time is not None for s in slots)
    assert all(s.appointment_time < time(12, 0) for s in slots)  # "morning" window


# ── slot taken while the patient was deciding ────────────────────────────────


async def test_slot_taken_while_deciding_is_handled_gracefully(clinic, db, redis):
    """A patient replies later and the exact slot they were offered is gone —
    never a crash, never a double-booking, offer another one instead."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    when = time(9, 0)
    filler = Patient(branch_id=branch.id, name="Filler", phone="+919666555000", age=50)
    db.add(filler)
    await db.flush()
    db.add(Token(
        branch_id=branch.id, doctor_id=doc.id, patient_id=filler.id,
        date=_tomorrow(), appointment_time=when, status="confirmed", source="walk_in",
    ))
    await db.commit()

    r = await wa_booking.confirm(
        db, branch, "919000000003", _slot_at(doc, when),
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )

    assert r.token is None
    assert r.taken is True
    assert r.alternatives, "must offer another slot"
    assert all(alt.appointment_time != when for alt in r.alternatives)


# ── RULE 4 — calendar write is part of the booking ───────────────────────────


async def test_calendar_failure_fails_the_booking(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["slot_doc"]
    slot = _slot_at(doc, time(10, 0))
    # Capture ids BEFORE the call. confirm() rolls the session back on a
    # calendar failure (it must — chat sessions outlive the request, and a
    # later wa_session commit would otherwise persist the dangling Token
    # insert), and rollback expires every ORM instance, so touching doc.id
    # afterwards would trigger a lazy load outside the greenlet context.
    doc_id, branch_id = doc.id, branch.id

    with pytest.raises(BookingFailed):
        await wa_booking.confirm(
            db, branch, "919000000004", slot,
            calendar_service=StubCalendar(raise_error=True), meta_service=StubMeta(),
        )

    assert await _token_count(db, branch) == 0  # nothing half-written
    redis_key = f"slot:{doc_id}:{branch_id}:{_tomorrow()}:1000"
    assert int(await redis.get(redis_key) or 0) == 0  # reservation released


async def test_calendar_failure_leaves_the_next_booking_unaffected(clinic, db, redis):
    """After a released reservation, a fresh confirm() for the SAME slot must
    succeed cleanly — proves the rollback+release left no residue."""
    branch, doc = clinic["branch"], clinic["slot_doc"]
    when = time(11, 0)
    # Build the retry slot BEFORE the failing call — the rollback inside
    # confirm() expires `doc`, so reading doc.id afterwards would lazy-load.
    retry_slot = _slot_at(doc, when)

    with pytest.raises(BookingFailed):
        await wa_booking.confirm(
            db, branch, "919000000005", _slot_at(doc, when),
            calendar_service=StubCalendar(raise_error=True), meta_service=StubMeta(),
        )

    r = await wa_booking.confirm(
        db, branch, "919000000005", retry_slot,
        calendar_service=StubCalendar(), meta_service=StubMeta(),
    )
    assert r.token is not None and r.token.status == "confirmed"


async def test_token_doctor_booking_never_touches_calendar(clinic, db, redis):
    """Token-queue doctors have no per-patient calendar event (bounce F2) — a
    calendar failure must never even be reachable for them."""
    branch, doc = clinic["branch"], clinic["token_doc"]
    cal = StubCalendar(raise_error=True)

    r = await wa_booking.confirm(
        db, branch, "919000000006", _token_slot(doc),
        calendar_service=cal, meta_service=StubMeta(),
    )

    assert r.token is not None
    assert cal.calls == 0


# ── RULE 4 — WhatsApp send failure never fails the booking ───────────────────


async def test_whatsapp_send_failure_never_fails_the_booking(clinic, db, redis):
    branch, doc = clinic["branch"], clinic["token_doc"]

    r = await wa_booking.confirm(
        db, branch, "919000000007", _token_slot(doc),
        calendar_service=StubCalendar(), meta_service=StubMeta(raise_error=True),
    )

    assert r.token is not None
    assert r.token.status == "confirmed"


# ── RULE 1 — branch isolation ────────────────────────────────────────────────


async def test_offer_slots_never_crosses_branches(db, redis):
    org_a = Organization(name="WaBookA", owner_phone="+919000900010",
                          owner_email=f"waa-{uuid.uuid4().hex[:6]}@test.com",
                          plan="clinic", status="active")
    org_b = Organization(name="WaBookB", owner_phone="+919000900011",
                          owner_email=f"wab-{uuid.uuid4().hex[:6]}@test.com",
                          plan="clinic", status="active")
    db.add_all([org_a, org_b])
    await db.flush()
    branch_a = Branch(org_id=org_a.id, name="A", whatsapp_number="+911100000010", status="active")
    branch_b = Branch(org_id=org_b.id, name="B", whatsapp_number="+911100000011", status="active")
    db.add_all([branch_a, branch_b])
    await db.flush()
    doc_a = Doctor(
        branch_id=branch_a.id, name="Dr A", specialization="general_physician",
        is_default_doctor=True, booking_type="token", schedule_mode="recurring",
        recurring_schedule={str(i): [{"start": "00:00", "end": "23:59"}] for i in range(7)},
        daily_token_limit=10, status="active",
    )
    # branch_b has its OWN doctor, so route_to_doctor's single-doctor fast
    # path resolves without an LLM call — the point is to prove doc_a (branch
    # A) is never returned for branch B, not to exercise LLM routing.
    doc_b = Doctor(
        branch_id=branch_b.id, name="Dr B", specialization="general_physician",
        is_default_doctor=True, booking_type="token", schedule_mode="recurring",
        recurring_schedule={str(i): [{"start": "00:00", "end": "23:59"}] for i in range(7)},
        daily_token_limit=10, status="active",
    )
    db.add_all([doc_a, doc_b])
    await db.commit()

    # Passing branch A's doctor_id against branch B must NEVER resolve to
    # branch A's doctor (RULE 1) — the mismatched id is silently ignored.
    slots = await wa_booking.offer_slots(
        db, branch_b, "tomorrow", doctor_id=doc_a.id, booking_date=_tomorrow(),
    )
    assert all(s.doctor_id != doc_a.id for s in slots)
    assert slots and slots[0].doctor_id == doc_b.id
