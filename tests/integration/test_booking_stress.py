"""Extensive booking stress: every doctor, every slot, repeated many times.

Vinay 2026-08-07: "test all doctors, their slots, their booking etc entirely.
and extensively. like 100 times and report."

Deliberately NO model in the loop. The model is tested live in
test_e2e_live_journey.py; what is under test here is the part that must never
be wrong no matter what the model asks for:

  RULE 2  no double-booking, ever — capacity is atomic
  RULE 3  a hold that does not become a booking is given back
          (and, since 2026-08-06, can never leave a negative counter)

Runs the REAL wa_booking.confirm path (Redis INCR + confirm_booking + the
duplicate guards). Only Google Calendar and Meta are stubbed.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, timedelta

import pytest
from sqlalchemy import func, select

from backend.models.schema import Branch, Doctor, Organization, Patient, Token
from backend.services import wa_booking
from backend.services.wa_booking import Slot

ITERATIONS = 100


class _Cal:
    async def create_booking_event(self, **kw) -> str:
        return f"evt-{uuid.uuid4().hex[:8]}"

    async def delete_event(self, *a, **kw) -> None:
        return None


class _Meta:
    def __getattr__(self, _n):
        async def _noop(*a, **kw):
            return True
        return _noop


def _kw():
    return {"calendar_service": _Cal(), "meta_service": _Meta()}


async def _clinic(db):
    org = Organization(
        name="Stress Org", owner_phone="+919000700011",
        owner_email=f"stress-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="Stress Clinic", status="active",
        timezone="Asia/Kolkata", address="1 Test Rd",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
        wa_phone_number_id=f"pnid-{uuid.uuid4().hex[:6]}",
    )
    db.add(br)
    await db.commit()
    return org, br


async def _doctor(db, br, name, *, booking_type="appointment",
                  slot_minutes=30, concurrent=1, start="09:00", end="13:00",
                  token_limit=20):
    doc = Doctor(
        branch_id=br.id, name=name, specialization="dental", status="active",
        booking_type=booking_type, slot_duration_minutes=slot_minutes,
        max_concurrent_per_slot=concurrent, daily_token_limit=token_limit,
        schedule_mode="recurring",
        recurring_schedule={str(d): [{"start": start, "end": end}] for d in range(7)},
    )
    db.add(doc)
    await db.commit()
    return doc


def _tomorrow():
    return date.today() + timedelta(days=1)


def _slot(doc, when, at=None, name="P", age=30):
    return Slot(
        doctor_id=doc.id, doctor_name=doc.name,
        booking_type=doc.booking_type or "appointment",
        date=when, appointment_time=at, patient_name=name, patient_age=age,
    )


async def _no_corrupt_keys(redis) -> list[str]:
    """RULE 2/3: no slot counter may be negative or immortal."""
    bad = []
    for pat in ("slot:*", "token:*"):
        async for k in redis.scan_iter(match=pat, count=500):
            v = await redis.get(k)
            ttl = await redis.ttl(k)
            try:
                if int(v) < 0:
                    bad.append(f"{k}={v} NEGATIVE")
            except (TypeError, ValueError):
                pass
            if ttl == -1:
                bad.append(f"{k} NO_TTL")
    return bad


@pytest.mark.asyncio
async def test_every_slot_of_every_doctor_books_exactly_once(db, redis):
    """Walk the FULL grid of several differently-configured doctors."""
    _org, br = await _clinic(db)
    docs = [
        await _doctor(db, br, "Srinivas", slot_minutes=30, concurrent=1),
        await _doctor(db, br, "Lakshmi", slot_minutes=15, concurrent=1,
                      start="10:00", end="12:00"),
        await _doctor(db, br, "Anitha", slot_minutes=60, concurrent=2,
                      start="09:00", end="12:00"),
    ]
    when = _tomorrow()
    total_booked = 0

    for doc in docs:
        slots = await wa_booking.offer_slots(
            db, br, "", doctor_id=doc.id, booking_date=when, limit=None,
        )
        times = sorted({s.appointment_time for s in slots if s.appointment_time})
        assert times, f"{doc.name} must publish a grid"
        cap = doc.max_concurrent_per_slot or 1

        for at in times:
            for seat in range(cap):
                phone = f"9198765{total_booked:05d}"
                r = await wa_booking.confirm(
                    db, br, phone,
                    _slot(doc, when, at, name=f"{doc.name}-{at}-{seat}"),
                    **_kw(),
                )
                assert r.token is not None, (
                    f"{doc.name} {at} seat {seat} refused: {r.reason}"
                )
                total_booked += 1

            # One seat past capacity must be refused — RULE 2.
            over = await wa_booking.confirm(
                db, br, "919000000999",
                _slot(doc, when, at, name=f"over-{doc.name}-{at}"), **_kw(),
            )
            assert over.token is None, f"{doc.name} {at} overbooked past {cap}"
            assert over.taken, f"expected a capacity refusal, got {over.reason}"

    # Every confirmed appointment is a distinct (doctor, time) seat set.
    rows = (await db.execute(
        select(Token.doctor_id, Token.appointment_time, func.count())
        .where(Token.branch_id == br.id, Token.status == "confirmed")
        .group_by(Token.doctor_id, Token.appointment_time)
    )).all()
    by_doc = {d.id: (d.max_concurrent_per_slot or 1) for d in docs}
    for doc_id, at, n in rows:
        assert n <= by_doc[doc_id], f"{at}: {n} bookings exceed capacity"

    assert not await _no_corrupt_keys(redis)
    print(f"\n  [stress] booked {total_booked} seats across {len(docs)} doctors, "
          f"every overflow refused, no corrupt keys")


@pytest.mark.asyncio
async def test_one_slot_under_concurrent_pressure_100_times(db, redis):
    """The invariant that matters most: N callers race for ONE seat, exactly
    one wins — repeated ITERATIONS times so a rare interleaving surfaces."""
    _org, br = await _clinic(db)
    # 5-minute grid over a long day so there are >= ITERATIONS distinct seats
    # to race for, one fresh seat per iteration.
    doc = await _doctor(db, br, "Race", slot_minutes=5, concurrent=1,
                        start="06:00", end="23:55")
    when = _tomorrow()
    slots = await wa_booking.offer_slots(
        db, br, "", doctor_id=doc.id, booking_date=when, limit=None,
    )
    times = sorted({s.appointment_time for s in slots if s.appointment_time})
    assert len(times) >= ITERATIONS, (
        f"need {ITERATIONS} distinct slots, grid has {len(times)}"
    )

    winners = 0
    for i in range(ITERATIONS):
        at = times[i]
        # Four callers, same seat, at once.
        results = await asyncio.gather(*[
            wa_booking.confirm(
                db, br, f"9199{i:04d}{c:04d}",
                _slot(doc, when, at, name=f"racer-{i}-{c}"), **_kw(),
            )
            for c in range(4)
        ], return_exceptions=True)
        ok = [r for r in results if not isinstance(r, Exception) and r.token is not None]
        assert len(ok) == 1, (
            f"iteration {i} at {at}: {len(ok)} winners for a 1-seat slot"
        )
        winners += 1

    confirmed = (await db.execute(
        select(func.count()).select_from(Token)
        .where(Token.branch_id == br.id, Token.status == "confirmed")
    )).scalar_one()
    assert confirmed == ITERATIONS, f"{confirmed} rows for {ITERATIONS} seats"
    assert not await _no_corrupt_keys(redis)
    print(f"\n  [stress] {ITERATIONS} concurrent races, exactly one winner each, "
          f"{confirmed} confirmed rows, no corrupt keys")


@pytest.mark.asyncio
async def test_token_queue_numbers_are_unique_and_monotonic(db, redis):
    """Queue doctors: the number IS the sequence — never reused, never 0."""
    _org, br = await _clinic(db)
    doc = await _doctor(db, br, "Queue", booking_type="token", token_limit=60)
    when = _tomorrow()

    numbers = []
    for i in range(60):
        r = await wa_booking.confirm(
            db, br, f"9197{i:06d}", _slot(doc, when, None, name=f"q{i}"), **_kw(),
        )
        assert r.token is not None, f"queue booking {i} refused: {r.reason}"
        numbers.append(r.token.token_number)

    assert len(set(numbers)) == len(numbers), "token numbers must be unique"
    assert min(numbers) >= 1, f"token numbers must start at 1, saw {min(numbers)}"
    assert numbers == sorted(numbers), "queue numbers must climb"
    assert not await _no_corrupt_keys(redis)
    print(f"\n  [stress] {len(numbers)} queue tokens: "
          f"{numbers[0]}..{numbers[-1]}, all unique, none <= 0")


@pytest.mark.asyncio
async def test_cancel_then_rebook_never_corrupts_the_counter(db, redis):
    """RULE 3 + the 2026-08-06 defect: repeated release/re-take must not drive
    a counter negative or leave it without a TTL."""
    _org, br = await _clinic(db)
    doc = await _doctor(db, br, "Churn", slot_minutes=30, concurrent=1)
    when = _tomorrow()
    at = (await wa_booking.offer_slots(
        db, br, "", doctor_id=doc.id, booking_date=when, limit=None,
    ))[0].appointment_time

    for i in range(ITERATIONS):
        r = await wa_booking.confirm(
            db, br, "919876500011", _slot(doc, when, at, name="Churn P"), **_kw(),
        )
        assert r.token is not None, f"cycle {i}: rebooking refused ({r.reason})"
        assert await wa_booking.cancel(db, br, "919876500011", str(r.token.id))
        bad = await _no_corrupt_keys(redis)
        assert not bad, f"cycle {i} corrupted Redis: {bad}"

    live = (await db.execute(
        select(func.count()).select_from(Token)
        .where(Token.branch_id == br.id, Token.status == "confirmed")
    )).scalar_one()
    assert live == 0, f"{live} bookings left confirmed after cancelling all"
    print(f"\n  [stress] {ITERATIONS} book/cancel cycles on one slot, "
          f"counter never negative, slot still bookable")


@pytest.mark.asyncio
async def test_family_members_on_one_number_stay_distinct(db, redis):
    """Many people share one phone. Each must stay their own patient record."""
    _org, br = await _clinic(db)
    doc = await _doctor(db, br, "Family", slot_minutes=15, concurrent=1)
    when = _tomorrow()
    times = sorted({
        s.appointment_time for s in await wa_booking.offer_slots(
            db, br, "", doctor_id=doc.id, booking_date=when, limit=None)
        if s.appointment_time
    })
    phone = "919876500011"
    names = ["Vinay", "Narayana", "Lakshmi Devi", "Ravi", "Sudha"]

    for i, nm in enumerate(names):
        r = await wa_booking.confirm(
            db, br, phone, _slot(doc, when, times[i], name=nm, age=30 + i),
            different_person=(i > 0), **_kw(),
        )
        assert r.token is not None, f"{nm} refused: {r.reason}"

    rows = (await db.execute(
        select(Patient.name).where(Patient.branch_id == br.id)
    )).scalars().all()
    for nm in names:
        assert nm in rows, f"{nm} collapsed into another record; got {rows}"
    assert len(set(rows)) == len(names), f"expected {len(names)} records, got {rows}"
    print(f"\n  [stress] {len(names)} family members on one number stayed distinct")
