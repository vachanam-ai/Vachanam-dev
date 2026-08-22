"""Two clinics due together must not queue behind each other's handoff."""

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import backend.jobs.pre_appt_reminder as job
from backend.models.schema import Branch, Doctor, Organization, Patient, Token


IST = ZoneInfo("Asia/Kolkata")


async def _seed_two_clinics(db, *, same_phone: bool = False) -> tuple[Token, Token]:
    now = datetime.now(IST)
    appointment = now + timedelta(minutes=20)
    org = Organization(
        id=uuid.uuid4(),
        name="Reminder concurrency org",
        owner_phone="+919000000091",
        owner_email=f"reminders-{uuid.uuid4()}@example.com",
        plan="clinic",
    )
    db.add(org)
    await db.flush()

    tokens = []
    for index in range(2):
        branch = Branch(
            id=uuid.uuid4(),
            org_id=org.id,
            name=f"Clinic {index}",
            did_number=f"+9180000000{index}",
            whatsapp_number=f"+9180000000{index}",
            timezone="Asia/Kolkata",
        )
        doctor = Doctor(
            id=uuid.uuid4(),
            branch_id=branch.id,
            name=f"Dr {index}",
            booking_type="appointment",
            pre_appointment_reminder=True,
            status="active",
        )
        patient = Patient(
            id=uuid.uuid4(),
            branch_id=branch.id,
            name=f"Patient {index}",
            phone="+919100000000" if same_phone else f"+9191000000{index}",
        )
        db.add_all([branch, doctor, patient])
        await db.flush()
        token = Token(
            id=uuid.uuid4(),
            branch_id=branch.id,
            doctor_id=doctor.id,
            patient_id=patient.id,
            token_number=index + 1,
            date=appointment.date(),
            appointment_time=appointment.time().replace(microsecond=0),
            status="confirmed",
            reminder_sent=False,
            source="voice",
            created_at=now - timedelta(days=1),
        )
        db.add(token)
        tokens.append(token)
    await db.commit()
    return tokens[0], tokens[1]


@pytest.mark.asyncio
async def test_due_clinics_start_delivery_concurrently(db, redis, monkeypatch):
    first, second = await _seed_two_clinics(db)
    started: set[uuid.UUID] = set()
    both_started = asyncio.Event()
    release = asyncio.Event()

    async def _blocked_delivery(branch, *_args, **_kwargs):
        started.add(branch.id)
        if len(started) == 2:
            both_started.set()
        await release.wait()
        return True

    monkeypatch.setattr(job, "_deliver_reminder", _blocked_delivery)
    run = asyncio.create_task(job.run_pre_appt_reminders())
    try:
        await asyncio.wait_for(both_started.wait(), timeout=1)
    finally:
        release.set()
        await run

    await db.refresh(first)
    await db.refresh(second)
    assert first.reminder_sent is True
    assert second.reminder_sent is True


@pytest.mark.asyncio
async def test_fast_handoff_is_marked_before_an_unrelated_slow_handoff_finishes(
    db, redis, monkeypatch
):
    fast, slow = await _seed_two_clinics(db)
    slow_started = asyncio.Event()
    release_slow = asyncio.Event()
    fast_marked = asyncio.Event()

    async def _delivery(_branch, _plan, token, *_args, **_kwargs):
        if token.id == fast.id:
            return True
        slow_started.set()
        await release_slow.wait()
        return True

    real_mark = job._mark_dispatched_if_no_dial_failure

    async def _observe_mark(session, token_id, expected_dial_attempts):
        result = await real_mark(session, token_id, expected_dial_attempts)
        if token_id == fast.id:
            fast_marked.set()
        return result

    monkeypatch.setattr(job, "_deliver_reminder", _delivery)
    monkeypatch.setattr(job, "_mark_dispatched_if_no_dial_failure", _observe_mark)
    run = asyncio.create_task(job.run_pre_appt_reminders())
    try:
        await asyncio.wait_for(slow_started.wait(), timeout=1)
        await asyncio.wait_for(fast_marked.wait(), timeout=1)
        assert not run.done()
        await db.refresh(fast)
        assert fast.reminder_sent is True
    finally:
        release_slow.set()
        await run


@pytest.mark.asyncio
async def test_same_handset_is_serialized_fairly_across_scheduler_ticks(
    db, redis, monkeypatch
):
    first, second = await _seed_two_clinics(db, same_phone=True)
    delivered = []

    async def _record_delivery(_branch, _plan, token, *_args, **_kwargs):
        delivered.append(token.id)
        return True

    monkeypatch.setattr(job, "_deliver_reminder", _record_delivery)

    await job.run_pre_appt_reminders()
    assert len(delivered) == 1

    await job.run_pre_appt_reminders()
    await db.refresh(first)
    await db.refresh(second)
    assert len(delivered) == 2
    assert len(set(delivered)) == 2
    assert first.reminder_sent is True
    assert second.reminder_sent is True


@pytest.mark.asyncio
async def test_same_handset_tries_healthy_sibling_after_first_handoff_fails(
    db, redis, monkeypatch
):
    failed, healthy = await _seed_two_clinics(db, same_phone=True)
    failed.reminder_30m_dial_attempts = 0
    healthy.reminder_30m_dial_attempts = 1
    await db.commit()
    attempted = []

    async def _fail_then_succeed(_branch, _plan, token, *_args, **_kwargs):
        attempted.append(token.id)
        return token.id == healthy.id

    monkeypatch.setattr(job, "_deliver_reminder", _fail_then_succeed)
    await job.run_pre_appt_reminders()

    await db.refresh(failed)
    await db.refresh(healthy)
    assert attempted == [failed.id, healthy.id]
    assert failed.reminder_sent is False
    assert healthy.reminder_sent is True


@pytest.mark.asyncio
async def test_same_handset_stops_after_first_success(db, redis, monkeypatch):
    first, second = await _seed_two_clinics(db, same_phone=True)
    first.reminder_30m_dial_attempts = 0
    second.reminder_30m_dial_attempts = 1
    await db.commit()
    attempted = []

    async def _always_succeeds(_branch, _plan, token, *_args, **_kwargs):
        attempted.append(token.id)
        return True

    monkeypatch.setattr(job, "_deliver_reminder", _always_succeeds)
    await job.run_pre_appt_reminders()

    await db.refresh(first)
    await db.refresh(second)
    assert attempted == [first.id]
    assert first.reminder_sent is True
    assert second.reminder_sent is False


@pytest.mark.asyncio
async def test_one_clinic_delivery_failure_does_not_cancel_the_other(
    db, redis, monkeypatch
):
    failed, succeeded = await _seed_two_clinics(db)

    async def _one_failure(_branch, _plan, token, *_args, **_kwargs):
        if token.id == failed.id:
            raise TimeoutError("one provider handoff stalled")
        return True

    monkeypatch.setattr(job, "_deliver_reminder", _one_failure)
    await job.run_pre_appt_reminders()

    await db.refresh(failed)
    await db.refresh(succeeded)
    assert failed.reminder_sent is False
    assert succeeded.reminder_sent is True


@pytest.mark.asyncio
async def test_fast_dial_failure_cannot_be_overwritten_as_sent(db, redis):
    token, _ = await _seed_two_clinics(db)

    # The voice worker got BUSY immediately and requeued before the scheduler
    # resumed from join verification.
    token.reminder_30m_dial_attempts = 1
    token.reminder_sent = False
    await db.commit()

    appointment_id = token.id
    marked = await job._mark_dispatched_if_no_dial_failure(
        db, appointment_id, expected_dial_attempts=0
    )

    await db.refresh(token)
    assert marked is False
    assert token.reminder_sent is False
    assert token.reminder_30m_dial_attempts == 1


@pytest.mark.asyncio
async def test_retry_preserves_the_first_dispatch_timestamp(db, redis):
    token, _ = await _seed_two_clinics(db)
    first_handoff = datetime.now(timezone.utc) - timedelta(minutes=12)
    token.reminder_30m_dispatched_at = first_handoff
    token.reminder_30m_dial_attempts = 2
    token.reminder_sent = False
    await db.commit()

    appointment_id = token.id
    marked = await job._mark_dispatched_if_no_dial_failure(
        db, appointment_id, expected_dial_attempts=2
    )

    await db.refresh(token)
    assert marked is True
    assert token.reminder_sent is True
    assert token.reminder_30m_dispatched_at == first_handoff
