"""Regression: a reminder must NOT be marked sent until the dispatch SUCCEEDS
(FIXLOG — Vinay's reminders went missing). The old code flipped reminder_sent
before dialing, so any dispatch failure permanently suppressed the call. Now a
failed dispatch leaves reminder_sent=False so the next tick retries; a successful
dispatch flips it True.
"""
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import backend.jobs.pre_appt_reminder as job
from backend.models.schema import Branch, Doctor, Organization, Patient, Token

IST = ZoneInfo("Asia/Kolkata")


async def _seed_in_window(db):
    """A confirmed appointment-doctor token whose time is ~20 min ahead (inside
    the [now, now+31] reminder window), reminder not yet sent."""
    now = datetime.now(IST)
    appt = (now + timedelta(minutes=20))
    org = Organization(id=uuid.uuid4(), name="Org", owner_phone="+919000000098",
                       owner_email="o@c.com", plan="clinic")
    db.add(org); await db.flush()
    br = Branch(id=uuid.uuid4(), org_id=org.id, name="C",
                did_number="+910000000099", whatsapp_number="+910000000099",
                timezone="Asia/Kolkata")
    db.add(br); await db.flush()
    doc = Doctor(id=uuid.uuid4(), branch_id=br.id, name="Dr A",
                 booking_type="appointment", pre_appointment_reminder=True, status="active")
    pat = Patient(id=uuid.uuid4(), branch_id=br.id, name="P", phone="+919000000099")
    db.add_all([doc, pat]); await db.flush()
    tok = Token(id=uuid.uuid4(), branch_id=br.id, doctor_id=doc.id, patient_id=pat.id,
                token_number=1, date=appt.date(), appointment_time=appt.time().replace(microsecond=0),
                status="confirmed", reminder_sent=False, source="voice",
                # Booked yesterday. Without this, created_at defaults to now and
                # the appointment is 20 minutes away — a booking made inside the
                # one-hour lead window, which by design gets no reminder at all
                # (booked_too_close). These tests are about dispatch/retry
                # behaviour, so the booking has to be one that qualifies.
                created_at=now - timedelta(days=1))
    db.add(tok); await db.commit()
    return tok


@pytest.mark.asyncio
async def test_failed_dispatch_leaves_reminder_unsent_for_retry(db, monkeypatch, redis):
    monkeypatch.setenv("LIVEKIT_URL", "wss://x")  # voice_plane_configured -> True
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    tok = await _seed_in_window(db)

    async def _fail(*a, **k):
        return False
    monkeypatch.setattr(job, "_dispatch_reminder_call", _fail)

    await job.run_pre_appt_reminders()

    await db.refresh(tok)  # the job committed on its own session — reload from DB
    assert tok.reminder_sent is False  # NOT marked → next tick retries


@pytest.mark.asyncio
async def test_successful_dispatch_marks_reminder_sent(db, monkeypatch, redis):
    monkeypatch.setenv("LIVEKIT_URL", "wss://x")
    monkeypatch.setenv("LIVEKIT_API_KEY", "k")
    tok = await _seed_in_window(db)

    called = {}

    async def _ok(branch, token, doctor, patient):
        called["token_id"] = token.id
        return True
    monkeypatch.setattr(job, "_dispatch_reminder_call", _ok)

    await job.run_pre_appt_reminders()

    assert called.get("token_id") == tok.id  # dispatch was attempted
    await db.refresh(tok)  # the job committed on its own session — reload from DB
    assert tok.reminder_sent is True
    assert tok.reminder_30m_dispatched_at is not None


@pytest.mark.asyncio
async def test_reminder_dial_guard_allows_only_current_confirmed_booking(db, redis):
    from agent.livekit_minimal.agent import _reminder_dial_state

    tok = await _seed_in_window(db)
    meta = {"call_type": "reminder", "token_id": str(tok.id), "branch_id": str(tok.branch_id)}
    state, lead = await _reminder_dial_state(meta)
    assert state == "ready"
    assert 0 <= lead <= 31 * 60

    tok.status = "cancelled_by_patient"
    await db.commit()
    assert (await _reminder_dial_state(meta))[0] == "not_confirmed"


@pytest.mark.asyncio
async def test_reminder_dial_guard_rejects_expired_or_early_dispatches(db, redis):
    from agent.livekit_minimal.agent import _reminder_dial_state

    tok = await _seed_in_window(db)
    meta = {"call_type": "reminder", "token_id": str(tok.id), "branch_id": str(tok.branch_id)}
    expired = datetime.now(IST) - timedelta(minutes=1)
    tok.date = expired.date()
    tok.appointment_time = expired.time()
    await db.commit()
    assert (await _reminder_dial_state(meta))[0] == "expired"

    early = datetime.now(IST) + timedelta(minutes=40)
    tok.date = early.date()
    tok.appointment_time = early.time()
    await db.commit()
    assert (await _reminder_dial_state(meta))[0] == "too_early"


# ── prod 2026-07-27: a reminder marked sent on agent-JOIN but whose outbound
#    DIAL then failed (callee BUSY on another clinic's simultaneous reminder to
#    the same number) was never retried. On dial failure we now reset
#    reminder_sent=False (bounded) so the next tick re-dials. ─────────────────

@pytest.mark.asyncio
async def test_failed_dial_requeues_reminder(db, redis):
    from agent.livekit_minimal.agent import _reminder_retry_on_dial_fail

    tok = await _seed_in_window(db)
    tok.reminder_sent = True  # the job flips this on agent-join, before the dial
    await db.commit()

    await _reminder_retry_on_dial_fail(
        {"call_type": "reminder", "token_id": str(tok.id), "branch_id": str(tok.branch_id)}
    )

    await db.refresh(tok)
    assert tok.reminder_sent is False  # requeued → the next tick re-dials


@pytest.mark.asyncio
async def test_dial_retry_is_bounded_by_attempt_cap(db, redis):
    from agent.livekit_minimal.agent import (
        _REMINDER_MAX_DIAL_ATTEMPTS,
        _reminder_retry_on_dial_fail,
    )

    tok = await _seed_in_window(db)
    meta = {"call_type": "reminder", "token_id": str(tok.id), "branch_id": str(tok.branch_id)}

    for _ in range(_REMINDER_MAX_DIAL_ATTEMPTS):  # attempts 1..cap → requeued
        tok.reminder_sent = True
        await db.commit()
        await _reminder_retry_on_dial_fail(meta)
        await db.refresh(tok)
        assert tok.reminder_sent is False

    tok.reminder_sent = True  # one past the cap → give up (a phone off all day)
    await db.commit()
    await _reminder_retry_on_dial_fail(meta)
    await db.refresh(tok)
    assert tok.reminder_sent is True  # exhausted → NOT reset again


@pytest.mark.asyncio
async def test_failed_dial_after_appointment_never_requeues(db, redis):
    from agent.livekit_minimal.agent import _reminder_retry_on_dial_fail

    tok = await _seed_in_window(db)
    tok.reminder_sent = True
    tok.appointment_time = (datetime.now(IST) - timedelta(minutes=1)).time()
    await db.commit()

    await _reminder_retry_on_dial_fail(
        {"call_type": "reminder", "token_id": str(tok.id), "branch_id": str(tok.branch_id)}
    )

    await db.refresh(tok)
    assert tok.reminder_sent is True
    assert tok.reminder_30m_dial_attempts == 0


@pytest.mark.asyncio
async def test_non_reminder_call_never_touches_token(db, redis):
    from agent.livekit_minimal.agent import _reminder_retry_on_dial_fail

    tok = await _seed_in_window(db)
    tok.reminder_sent = True
    await db.commit()

    # followups self-heal via task status — this path is reminder-only.
    await _reminder_retry_on_dial_fail({"call_type": "followup", "task_id": "x"})
    await _reminder_retry_on_dial_fail({"call_type": "reminder"})  # no token_id

    await db.refresh(tok)
    assert tok.reminder_sent is True  # untouched


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))


def test_stdlib_logger_calls_use_only_supported_keywords():
    """Structured kwargs on ``logging.Logger`` crash the whole voice job."""
    import ast
    from pathlib import Path

    tree = ast.parse(Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8"))
    allowed = {"exc_info", "stack_info", "stacklevel", "extra"}
    invalid = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        target = node.func.value
        if not isinstance(target, ast.Name) or target.id != "logger":
            continue
        if node.func.attr not in {"debug", "info", "warning", "error", "exception", "critical"}:
            continue
        bad = [kw.arg for kw in node.keywords if kw.arg not in allowed]
        if bad:
            invalid.append((node.lineno, node.func.attr, bad))
    assert invalid == []