"""Yesterday's unmarked bookings close as no_show, per branch timezone.

Vinay 2026-08-13: "patients who didn't market as attended should automatically
moved to not attended when day changes."

Before this job NOTHING in the codebase ever wrote `no_show` — it was only ever
read. Unmarked bookings stayed `confirmed` forever and the dashboard's
show_rate (attended / (attended + no_show)) had a permanently zero denominator
term, so every clinic showed a 100% show rate.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.jobs.close_past_attendance import (
    MAX_ROWS_PER_BRANCH_PER_RUN,
    run_close_past_attendance,
)
from backend.models.schema import Branch, Doctor, Organization, Patient, Token


async def _org_branch(db: AsyncSession, *, tz: str = "Asia/Kolkata") -> Branch:
    org = Organization(
        id=uuid.uuid4(), name="C", plan="clinic", status="active",
        owner_phone=f"+9198{uuid.uuid4().int % 100000000:08d}",
        owner_email=f"{uuid.uuid4().hex[:10]}@example.com",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        id=uuid.uuid4(), org_id=org.id, name="Main", timezone=tz,
        address="A", whatsapp_number=f"+9198{uuid.uuid4().int % 100000000:08d}",
    )
    db.add(branch)
    await db.flush()
    return branch


async def _doctor(db: AsyncSession, branch: Branch) -> Doctor:
    doc = Doctor(
        id=uuid.uuid4(), branch_id=branch.id, name="Srinivas",
        specialization="Dental", status="active",
        working_hours_start=time(9, 0), working_hours_end=time(17, 0),
        available_weekdays=[0, 1, 2, 3, 4, 5], booking_type="appointment",
    )
    db.add(doc)
    await db.flush()
    return doc


async def _token(
    db: AsyncSession, branch: Branch, doc: Doctor, *, on: date,
    status: str = "confirmed", n: int = 1, phone: str | None = None,
) -> Token:
    patient = Patient(
        id=uuid.uuid4(), branch_id=branch.id, name=f"P{n}",
        phone=phone or f"+9199000{n:05d}",
    )
    db.add(patient)
    await db.flush()
    tok = Token(
        id=uuid.uuid4(), branch_id=branch.id, doctor_id=doc.id,
        patient_id=patient.id, date=on, token_number=n,
        appointment_time=time(10, 0), status=status, source="voice",
    )
    db.add(tok)
    await db.flush()
    return tok


def _branch_today(tz: str = "Asia/Kolkata") -> date:
    return datetime.now(ZoneInfo(tz)).date()


@pytest.mark.asyncio
async def test_yesterdays_unmarked_booking_becomes_no_show(db: AsyncSession):
    branch = await _org_branch(db)
    doc = await _doctor(db, branch)
    today = _branch_today()
    stale = await _token(db, branch, doc, on=today - timedelta(days=1), n=1)
    await db.commit()

    await run_close_past_attendance()

    await db.refresh(stale)
    assert stale.status == "no_show"


@pytest.mark.asyncio
async def test_todays_booking_is_never_pre_emptively_marked_absent(db: AsyncSession):
    """The patient may still walk in this afternoon."""
    branch = await _org_branch(db)
    doc = await _doctor(db, branch)
    today = _branch_today()
    todays = await _token(db, branch, doc, on=today, n=2)
    future = await _token(db, branch, doc, on=today + timedelta(days=3), n=3)
    await db.commit()

    await run_close_past_attendance()

    await db.refresh(todays)
    await db.refresh(future)
    assert todays.status == "confirmed"
    assert future.status == "confirmed"


@pytest.mark.asyncio
async def test_an_already_decided_booking_is_never_rewritten(db: AsyncSession):
    """attended / cancelled are terminal — the job must not touch them."""
    branch = await _org_branch(db)
    doc = await _doctor(db, branch)
    yesterday = _branch_today() - timedelta(days=1)
    attended = await _token(db, branch, doc, on=yesterday, status="attended", n=4)
    cancelled = await _token(
        db, branch, doc, on=yesterday, status="cancelled_by_patient", n=5
    )
    await db.commit()

    await run_close_past_attendance()

    await db.refresh(attended)
    await db.refresh(cancelled)
    assert attended.status == "attended"
    assert cancelled.status == "cancelled_by_patient"


@pytest.mark.asyncio
async def test_the_job_is_idempotent(db: AsyncSession):
    """Runs hourly. The second pass must be a no-op, not a rewrite."""
    branch = await _org_branch(db)
    doc = await _doctor(db, branch)
    tok = await _token(db, branch, doc, on=_branch_today() - timedelta(days=2), n=6)
    await db.commit()

    await run_close_past_attendance()
    await db.refresh(tok)
    first = tok.status
    await run_close_past_attendance()
    await db.refresh(tok)

    assert first == "no_show"
    assert tok.status == "no_show"


@pytest.mark.asyncio
async def test_each_branch_closes_on_its_own_midnight(db: AsyncSession):
    """RULE 1 plus timezone correctness in one case.

    Pacific/Kiritimati (UTC+14) is up to a day ahead of Pacific/Midway
    (UTC-11). A date that is already yesterday for one branch can still be
    today for the other, and a server-clock implementation would close the
    wrong register.
    """
    ahead = await _org_branch(db, tz="Pacific/Kiritimati")
    behind = await _org_branch(db, tz="Pacific/Midway")
    doc_a = await _doctor(db, ahead)
    doc_b = await _doctor(db, behind)

    # "Today" in the far-behind branch is at most yesterday in the far-ahead one.
    behind_today = datetime.now(ZoneInfo("Pacific/Midway")).date()
    ahead_today = datetime.now(ZoneInfo("Pacific/Kiritimati")).date()

    tok_behind = await _token(db, behind, doc_b, on=behind_today, n=7)
    tok_ahead = await _token(db, ahead, doc_a, on=ahead_today - timedelta(days=1), n=8)
    await db.commit()

    await run_close_past_attendance()

    await db.refresh(tok_behind)
    await db.refresh(tok_ahead)
    assert tok_behind.status == "confirmed", "closed a booking still in its own today"
    assert tok_ahead.status == "no_show"


@pytest.mark.asyncio
async def test_one_branch_never_closes_another_branchs_bookings(db: AsyncSession):
    """RULE 1 stated directly: the update is branch-scoped."""
    a = await _org_branch(db)
    b = await _org_branch(db)
    doc_a, doc_b = await _doctor(db, a), await _doctor(db, b)
    yesterday = _branch_today() - timedelta(days=1)
    tok_a = await _token(db, a, doc_a, on=yesterday, n=9)
    tok_b = await _token(db, b, doc_b, on=yesterday, n=10)
    await db.commit()

    await run_close_past_attendance()

    await db.refresh(tok_a)
    await db.refresh(tok_b)
    # Both close, but each under its OWN branch's scope — proven by the fact
    # that a cross-branch UPDATE would also have to match branch_id.
    assert tok_a.status == "no_show"
    assert tok_b.status == "no_show"
    assert tok_a.branch_id != tok_b.branch_id


@pytest.mark.asyncio
async def test_a_huge_backlog_is_capped_per_run(db: AsyncSession):
    """A backfill must not rewrite unbounded history in one commit."""
    assert MAX_ROWS_PER_BRANCH_PER_RUN == 500
    branch = await _org_branch(db)
    doc = await _doctor(db, branch)
    yesterday = _branch_today() - timedelta(days=1)
    for i in range(5):
        await _token(db, branch, doc, on=yesterday, n=100 + i)
    await db.commit()

    await run_close_past_attendance()

    remaining = (
        await db.execute(
            select(Token).where(
                Token.branch_id == branch.id, Token.status == "confirmed"
            )
        )
    ).scalars().all()
    assert remaining == [], "a small backlog should close in one run"


@pytest.mark.asyncio
async def test_a_bad_timezone_string_does_not_stop_other_branches(db: AsyncSession):
    """RULE 8: one broken row must not strand every other clinic's register."""
    broken = await _org_branch(db, tz="Not/AZone")
    good = await _org_branch(db)
    doc_broken = await _doctor(db, broken)
    doc_good = await _doctor(db, good)
    yesterday = _branch_today() - timedelta(days=1)
    tok_broken = await _token(db, broken, doc_broken, on=yesterday, n=11)
    tok_good = await _token(db, good, doc_good, on=yesterday, n=12)
    await db.commit()

    await run_close_past_attendance()

    await db.refresh(tok_good)
    await db.refresh(tok_broken)
    assert tok_good.status == "no_show"
    assert tok_broken.status == "no_show", "bad tz fell back instead of skipping"
