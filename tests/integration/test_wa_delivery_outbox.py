"""Proof that patient-event WhatsApp sends are durable and idempotent."""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from backend.models.schema import (
    Branch, Organization, WhatsAppDelivery,
)
from backend.services import meta_service, wa_delivery, wa_service

pytestmark = pytest.mark.asyncio


async def _branch(db):
    org = Organization(
        name="Outbox Org",
        owner_phone="+919999000001",
        owner_email=f"wa-outbox-{uuid.uuid4().hex[:8]}@test.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="Outbox Clinic",
        whatsapp_number=f"+9188{uuid.uuid4().int % 100000000:08d}",
        timezone="Asia/Kolkata",
        status="active",
        wa_phone_number_id="wa-phone-id",
    )
    db.add(branch)
    await db.commit()
    return branch


async def test_same_booking_event_is_sent_exactly_once(db, monkeypatch):
    branch = await _branch(db)
    sends = []

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)

    async def sent(*args, **kwargs):
        sends.append(args)
        return True

    monkeypatch.setattr(meta_service, "send_purpose", sent)
    kwargs = dict(
        branch_id=branch.id,
        recipient_phone="+919876500001",
        purpose="booking_confirm",
        values=["Anjali", "Clinic", "Srinivas", "12 August", "10:30 AM"],
        event_key="booking:token-1",
    )
    assert await wa_delivery.enqueue(**kwargs) is True
    assert await wa_delivery.enqueue(**kwargs) is True

    assert len(sends) == 1
    count = (
        await db.execute(select(func.count()).select_from(WhatsAppDelivery))
    ).scalar_one()
    assert count == 1
    row = (await db.execute(select(WhatsAppDelivery))).scalar_one()
    assert row.status == "sent"
    assert row.attempts == 0


async def test_transient_failure_is_persisted_then_retried(db, monkeypatch):
    branch = await _branch(db)
    outcomes = iter((False, True))

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)

    async def flaky(*args, **kwargs):
        return next(outcomes)

    monkeypatch.setattr(meta_service, "send_purpose", flaky)
    assert await wa_delivery.enqueue(
        branch.id,
        "+919876500002",
        "cancel",
        ["Anjali", "Srinivas", "12 August", "10:30 AM"],
        event_key="cancel:token-2",
    ) is False

    db.expire_all()
    task = (await db.execute(select(WhatsAppDelivery))).scalar_one()
    assert task.status == "pending"
    assert task.attempts == 1

    assert await wa_delivery.deliver(task.id) is True
    db.expire_all()
    task = (await db.execute(select(WhatsAppDelivery))).scalar_one()
    assert task.status == "sent"
    assert task.attempts == 1
    assert task.sent_at is not None


async def test_concurrent_enqueue_claims_event_once(db, monkeypatch):
    branch = await _branch(db)
    sends = 0
    entered = asyncio.Event()

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)

    async def slow_send(*args, **kwargs):
        nonlocal sends
        sends += 1
        entered.set()
        await asyncio.sleep(0.05)
        return True

    monkeypatch.setattr(meta_service, "send_purpose", slow_send)
    kwargs = dict(
        branch_id=branch.id,
        recipient_phone="+919876500003",
        purpose="booking_confirm",
        values=["Anjali", "Clinic", "Srinivas", "12 August", "10:30 AM"],
        event_key="booking:concurrent-token",
    )
    first = asyncio.create_task(wa_delivery.enqueue(**kwargs))
    await entered.wait()
    second = asyncio.create_task(wa_delivery.enqueue(**kwargs))
    await asyncio.gather(first, second)

    assert sends == 1
