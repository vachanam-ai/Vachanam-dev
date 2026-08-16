"""Channel preferences never lose a reminder or follow-up."""
from types import SimpleNamespace as NS
from uuid import uuid4

import pytest


def _objects(*, reminder_calls=False):
    branch = NS(
        id=uuid4(), reminder_calls_enabled=reminder_calls,
        followup_calls_enabled=False, timezone="Asia/Kolkata",
    )
    token = NS(id=uuid4())
    doctor = NS(id=uuid4(), name="Srinivas")
    patient = NS(id=uuid4(), name="Anjali", phone="+919876543210")
    return branch, token, doctor, patient


@pytest.mark.asyncio
async def test_whatsapp_only_reminder_does_not_spend_voice_minutes(monkeypatch):
    from backend.jobs import pre_appt_reminder as job
    from backend.services import wa_readiness

    branch, token, doctor, patient = _objects(reminder_calls=False)

    async def ready(*args, **kwargs):
        return {"reminder": True}

    async def accepted(*args, **kwargs):
        return True

    async def must_not_call(*args, **kwargs):
        raise AssertionError("voice dispatch ran despite WhatsApp-only preference")

    monkeypatch.setattr(wa_readiness, "purpose_readiness", ready)
    monkeypatch.setattr(job, "_send_wa_reminder", accepted)
    monkeypatch.setattr(job, "_dispatch_reminder_call", must_not_call)

    assert await job._deliver_reminder(
        branch, "clinic", token, doctor, patient,
        reminder_kind="30m", voice_plane_configured=True,
    ) is True


@pytest.mark.asyncio
async def test_whatsapp_failure_forces_voice_even_when_preference_is_off(monkeypatch):
    from backend.jobs import pre_appt_reminder as job
    from backend.services import wa_readiness

    branch, token, doctor, patient = _objects(reminder_calls=False)
    called = []

    async def not_ready(*args, **kwargs):
        return {"reminder": False}

    async def voice(*args, **kwargs):
        called.append(token.id)
        return True

    monkeypatch.setattr(wa_readiness, "purpose_readiness", not_ready)
    monkeypatch.setattr(job, "_dispatch_reminder_call", voice)

    assert await job._deliver_reminder(
        branch, "clinic", token, doctor, patient,
        reminder_kind="30m", voice_plane_configured=True,
    ) is True
    assert called == [token.id]


@pytest.mark.asyncio
async def test_disconnect_restores_both_voice_fallbacks(db):
    from backend.models.schema import Branch, Organization
    from backend.services.wa_lifecycle import disconnect_branch

    org = Organization(
        name="Channels", owner_phone="+919000000041",
        owner_email=f"channels-{uuid4().hex[:8]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="Clinic",
        whatsapp_number=f"+9188{uuid4().int % 100000000:08d}",
        wa_status="connected", wa_phone_number_id="meta-number",
        reminder_calls_enabled=False, followup_calls_enabled=False,
    )
    db.add(branch)
    await db.flush()

    await disconnect_branch(db, branch)
    await db.commit()
    await db.refresh(branch)

    assert branch.wa_status == "disconnected"
    assert branch.reminder_calls_enabled is True
    assert branch.followup_calls_enabled is True
