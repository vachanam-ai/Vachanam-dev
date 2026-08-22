"""A handset collision defers work; it is not a failed patient attempt."""

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest

from backend.jobs import wake_gate
from backend.models.schema import (
    Branch,
    ClinicQuestion,
    Doctor,
    FollowupTask,
    Organization,
    Patient,
    Token,
)


async def _clinic(db):
    org = Organization(
        id=uuid.uuid4(),
        name="Deferred outbound org",
        owner_phone="+919000000080",
        owner_email=f"deferred-{uuid.uuid4()}@example.com",
        plan="clinic",
        status="active",
    )
    branch = Branch(
        id=uuid.uuid4(),
        org_id=org.id,
        name="Deferred outbound branch",
        did_number="+918000000080",
        whatsapp_number="+918000000080",
        timezone="Asia/Kolkata",
        status="active",
    )
    db.add_all([org, branch])
    await db.flush()
    doctor = Doctor(
        id=uuid.uuid4(),
        branch_id=branch.id,
        name="Dr Deferred",
        booking_type="token",
        status="active",
    )
    patient = Patient(
        id=uuid.uuid4(),
        branch_id=branch.id,
        name="Deferred Patient",
        phone="+919100000080",
        followup_consent=True,
    )
    db.add_all([doctor, patient])
    await db.flush()
    return branch, doctor, patient


async def _always_run(_name):
    return True


async def _ignore_next_at(_name, _when):
    return None


def _enable_job(monkeypatch):
    monkeypatch.setattr(wake_gate, "should_run_scheduled", _always_run)
    monkeypatch.setattr(wake_gate, "set_next_at", _ignore_next_at)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dispatch_result", "expected_attempts", "expected_status"),
    [(None, 2, "pending"), (False, 3, "unreachable")],
)
async def test_followup_deferred_does_not_burn_attempt_but_failure_does(
    db, redis, monkeypatch, dispatch_result, expected_attempts, expected_status
):
    from backend.jobs import next_visit_followup_caller as job
    from backend.services import wa_readiness

    branch, doctor, patient = await _clinic(db)
    task = FollowupTask(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        task_type="next_visit_book",
        channel="voice",
        status="pending",
        scheduled_date=date.today(),
        attempt_count=2,
        max_attempts=3,
    )
    db.add(task)
    await db.commit()
    _enable_job(monkeypatch)

    async def _not_wa(*_args, **_kwargs):
        return {"followup": False}

    async def _dispatch(*_args, **_kwargs):
        return dispatch_result

    monkeypatch.setattr(wa_readiness, "purpose_readiness", _not_wa)
    monkeypatch.setattr(job, "_dispatch", _dispatch)
    await job.run_next_visit_followups(
        now=datetime(2026, 8, 22, 11, 0, tzinfo=job.IST)
    )

    await db.refresh(task)
    assert task.attempt_count == expected_attempts
    assert task.status == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dispatch_result", "expected_attempts", "expected_status"),
    [(None, 2, "answered"), (False, 3, "unreachable")],
)
async def test_question_deferred_does_not_burn_attempt_but_failure_does(
    db, redis, monkeypatch, dispatch_result, expected_attempts, expected_status
):
    from backend.jobs import question_callback_caller as job

    branch, _doctor, patient = await _clinic(db)
    question = ClinicQuestion(
        branch_id=branch.id,
        patient_id=patient.id,
        question="Can the doctor call me back?",
        answer="Yes.",
        caller_last4=patient.phone[-4:],
        caller_phone=patient.phone,
        status="answered",
        call_attempts=2,
    )
    db.add(question)
    await db.commit()
    _enable_job(monkeypatch)

    async def _dispatch(*_args, **_kwargs):
        return dispatch_result

    monkeypatch.setattr(job, "_dispatch", _dispatch)
    await job.run_question_callbacks(
        now=datetime(2026, 8, 22, 11, 0, tzinfo=job.IST)
    )

    await db.refresh(question)
    assert question.call_attempts == expected_attempts
    assert question.status == expected_status


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("dispatch_result", "expected_attempts", "expected_status"),
    [(None, 2, "pending"), (False, 3, "unreachable")],
)
async def test_cascade_deferred_does_not_burn_attempt_but_failure_does(
    db, redis, monkeypatch, dispatch_result, expected_attempts, expected_status
):
    from backend.jobs import cascade_rebook_caller as job

    branch, doctor, patient = await _clinic(db)
    token = Token(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        date=date.today() + timedelta(days=1),
        token_number=1,
        source="voice",
        status="cancelled_by_clinic",
    )
    db.add(token)
    await db.flush()
    scheduled_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    task = FollowupTask(
        branch_id=branch.id,
        doctor_id=doctor.id,
        patient_id=patient.id,
        token_id=token.id,
        task_type="cascade_rebook",
        channel="voice",
        status="pending",
        scheduled_at=scheduled_at,
        attempt_count=2,
        max_attempts=3,
    )
    db.add(task)
    await db.commit()
    _enable_job(monkeypatch)
    monkeypatch.setenv("LIVEKIT_URL", "wss://test.invalid")
    monkeypatch.setenv("LIVEKIT_API_KEY", "test")
    monkeypatch.setattr(job, "branch_outbound_trunk_id", lambda _branch: "trunk")

    async def _dispatch(*_args, **_kwargs):
        return dispatch_result

    monkeypatch.setattr(job, "_dispatch_rebook_call", _dispatch)
    await job.run_cascade_rebook_calls()

    await db.refresh(task)
    assert task.attempt_count == expected_attempts
    assert task.status == expected_status
    if dispatch_result is None:
        assert task.scheduled_at == scheduled_at
