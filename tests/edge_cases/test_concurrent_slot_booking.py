"""SEC #1 (2026-07-11 audit): slot-doctor double-booking race.

A slot/appointment doctor has NO token-number unique index (that backstop is
token-doctors only). Before this fix, two concurrent confirm_booking calls for
the same max_concurrent_per_slot=1 slot both read count=0 and both INSERT —
two patients in a one-capacity slot. The per-slot advisory lock in
confirm_booking must now let exactly ONE win.

N concurrent callers, one 1-capacity slot → exactly 1 success, N-1 slot_full,
and exactly 1 confirmed Token row in the DB.
"""
import asyncio
from datetime import date, time, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from agent.tools.booking_tools import confirm_booking
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor, Organization, Token


class _OkCal:
    async def create_booking_event(self, **kw):
        return "evt_fake_123"

    async def delete_event(self, *a):
        return None


class _NullMeta:
    async def send_booking_confirmation(self, **kw):
        return None


@pytest_asyncio.fixture
async def slot_clinic(db):
    org = Organization(
        name="Slot Race Clinic", owner_phone="+919911002200",
        owner_email="slotrace@test.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="Slot Branch",
        whatsapp_number="+911234500011", status="active",
        google_calendar_id="cal@group.calendar.google.com",
    )
    db.add(branch)
    await db.flush()
    doctor = Doctor(
        branch_id=branch.id, name="Dr. Slot", booking_type="appointment",
        working_hours_start=time(9, 0), working_hours_end=time(17, 0),
        slot_duration_minutes=30, max_concurrent_per_slot=1,
        available_weekdays=[0, 1, 2, 3, 4, 5, 6], is_default_doctor=True,
        google_calendar_id="cal@group.calendar.google.com", status="active",
    )
    db.add(doctor)
    await db.commit()
    return {"branch": branch, "doctor": doctor}


@pytest.mark.asyncio
async def test_concurrent_confirms_one_slot_only_one_wins(slot_clinic, redis):
    branch = slot_clinic["branch"]
    doctor = slot_clinic["doctor"]
    when = date.today() + timedelta(days=3)
    slot = time(10, 0)
    N = 12

    sem = asyncio.Semaphore(8)

    async def one(i):
        async with sem:
            async with AsyncSessionLocal() as session:
                res = await confirm_booking(
                    doctor_id=doctor.id, branch_id=branch.id,
                    patient_name=f"Racer {i}", patient_phone=f"+9198000000{i:02d}",
                    complaint="checkup", booking_date=when, token_number=1,
                    followup_consent=False, appointment_time=slot, source="voice",
                    db=session, calendar_service=_OkCal(), meta_service=_NullMeta(),
                    patient_age=30,
                )
                if res.get("success"):
                    await session.commit()
                else:
                    await session.rollback()
                return res

    results = await asyncio.gather(*[one(i) for i in range(N)])
    wins = [r for r in results if r.get("success")]
    assert len(wins) == 1, f"expected exactly 1 winner, got {len(wins)}: {results}"
    assert all(r.get("reason") == "slot_full" for r in results if not r.get("success"))

    # DB truth: exactly one confirmed booking in that slot.
    async with AsyncSessionLocal() as s:
        n = (await s.execute(
            select(func.count()).select_from(Token).where(
                Token.branch_id == branch.id, Token.doctor_id == doctor.id,
                Token.date == when, Token.appointment_time == slot,
                Token.status == "confirmed",
            )
        )).scalar_one()
    assert n == 1, f"slot overbooked: {n} confirmed rows"
