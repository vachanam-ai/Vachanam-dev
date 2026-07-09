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
from sqlalchemy import select

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
                status="confirmed", reminder_sent=False, source="voice")
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


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
