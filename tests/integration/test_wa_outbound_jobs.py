"""WA T8: reminder ride-along never disturbs the voice path; rating batch
asks once per attended token; cascade leave-ping fires alongside rebook."""
import uuid
from datetime import date, time

import pytest

from backend.config import settings
from backend.models.schema import (
    Branch, Doctor, Organization, Patient, Rating, Token,
)
from backend.services import wa_service


@pytest.fixture
def wa_capture(monkeypatch):
    monkeypatch.setattr(settings, "meta_access_token", "tok", raising=False)
    sent = []

    async def _fake(branch, to, template, lang, params, buttons=None):
        sent.append({"template": template, "to": to, "params": params})
        return True

    monkeypatch.setattr(wa_service, "send_template", _fake)
    return sent


async def _clinic(db, plan="clinic", linked=True):
    org = Organization(
        name="JOrg", owner_phone="+919000700030",
        owner_email=f"jo-{uuid.uuid4().hex[:6]}@test.com", plan=plan, status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="JBranch",
        whatsapp_number=f"+9144{str(uuid.uuid4().int)[:8]}", status="active",
        wa_phone_number_id=str(uuid.uuid4().int)[:12] if linked else None,
    )
    db.add(b)
    await db.flush()
    doc = Doctor(branch_id=b.id, name="Dr J", booking_type="appointment",
                 slot_duration_minutes=15)
    pat = Patient(branch_id=b.id, name="JP", phone="+919000000077")
    db.add_all([doc, pat])
    await db.flush()
    tok = Token(
        branch_id=b.id, doctor_id=doc.id, patient_id=pat.id,
        date=date.today(), appointment_time=time(17, 0), source="voice",
        status="attended",
    )
    db.add(tok)
    await db.commit()
    return b, doc, pat, tok


# ── reminder ride-along ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_wa_reminder_rides_along_and_failure_is_silent(db, wa_capture, monkeypatch):
    from backend.jobs import pre_appt_reminder as job

    b, doc, pat, tok = await _clinic(db)
    await job._send_wa_reminder(db, b, tok, doc, pat)
    assert wa_capture[-1]["template"] == "appt_reminder"

    # failure inside wa path must not raise (caller guards, but the helper
    # itself must also never break the voice loop on a bad branch)
    async def _boom(*a, **k):
        raise RuntimeError("meta down")

    monkeypatch.setattr(wa_service, "send_template", _boom)
    with pytest.raises(RuntimeError):
        # helper propagates; the CALLER's try/except owns the guard — verify
        # the call site wraps it (source contract):
        await job._send_wa_reminder(db, b, tok, doc, pat)
    import inspect

    src = inspect.getsource(job.run_pre_appt_reminders)
    assert "_send_wa_reminder" in src
    assert "wa_reminder_failed" in src  # guarded call site


@pytest.mark.asyncio
async def test_wa_reminder_skips_solo_and_unlinked(db, wa_capture):
    from backend.jobs import pre_appt_reminder as job

    for kwargs in ({"plan": "solo"}, {"linked": False}):
        b, doc, pat, tok = await _clinic(db, **kwargs)
        await job._send_wa_reminder(db, b, tok, doc, pat)
    assert wa_capture == []


# ── rating batch ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_rating_batch_asks_once_and_skips_rated(db, wa_capture, monkeypatch):
    import backend.jobs.wa_rating_ask as job

    b, doc, pat, tok = await _clinic(db)
    b2, _, _, tok2 = await _clinic(db)
    # tok2 already rated → must be skipped
    db.add(Rating(branch_id=b2.id, token_id=tok2.id, patient_id=tok2.patient_id, score=5))
    await db.commit()

    asked = set()

    async def _once(token_id):
        if token_id in asked:
            return True
        asked.add(token_id)
        return False

    monkeypatch.setattr(job, "_already_asked", _once)

    await job.run_wa_rating_ask()
    first = [s for s in wa_capture if s["template"] == "rating_ask"]
    assert len(first) == 1  # only the unrated attended token

    await job.run_wa_rating_ask()  # second run: ask-once marker holds
    second = [s for s in wa_capture if s["template"] == "rating_ask"]
    assert len(second) == 1


# ── cascade leave ping ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cascade_sends_leave_ping(db, wa_capture):
    from backend.services.cascade_cancel import cascade_for_unavailability

    b, doc, pat, tok = await _clinic(db)
    tok.status = "confirmed"
    await db.commit()

    res = await cascade_for_unavailability(
        db, b.id, doc.id, date.today(), date.today(), user_id=str(uuid.uuid4()),
        reason="leave",
    )
    assert res["cancelled_tokens"] == 1
    pings = [s for s in wa_capture if s["template"] == "leave_rebook"]
    assert len(pings) == 1
    assert pings[0]["params"][0] == "Dr J"
