"""Proof that patient-event WhatsApp sends are durable and idempotent."""
import asyncio
import uuid

import pytest
from sqlalchemy import func, select

from backend.models.schema import (
    Branch, Organization, WhatsAppDelivery,
)
from backend.services import meta_service, wa_delivery, wa_service
from backend.services.wa_lifecycle import disconnect_branch

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
        wa_status="connected",
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


async def test_provider_send_does_not_hold_an_outbox_db_connection(db, monkeypatch):
    """A two-slot production pool must have room for Meta's own DB lookup."""
    branch = await _branch(db)
    real_factory = wa_delivery._db_module.AsyncSessionLocal
    active = 0

    class TrackedSession:
        def __init__(self):
            self._context = real_factory()

        async def __aenter__(self):
            nonlocal active
            session = await self._context.__aenter__()
            active += 1
            return session

        async def __aexit__(self, *args):
            nonlocal active
            try:
                return await self._context.__aexit__(*args)
            finally:
                active -= 1

    monkeypatch.setattr(
        wa_delivery._db_module, "AsyncSessionLocal", lambda: TrackedSession()
    )
    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)

    async def sent(*args, **kwargs):
        assert active == 0
        return True

    monkeypatch.setattr(meta_service, "send_purpose", sent)
    assert await wa_delivery.enqueue(
        branch.id,
        "+919876500020",
        "cancel",
        ["Anjali", "Srinivas", "12 August", "10:30 AM"],
        event_key="cancel:no-held-pool-slot",
    ) is True


async def test_background_delivery_does_not_hold_the_voice_tool(db, monkeypatch):
    branch = await _branch(db)
    entered = asyncio.Event()
    release = asyncio.Event()

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)

    async def slow_send(*args, **kwargs):
        entered.set()
        await release.wait()
        return True

    monkeypatch.setattr(meta_service, "send_purpose", slow_send)
    assert await wa_delivery.enqueue(
        branch.id,
        "+919876500021",
        "reschedule",
        ["Anjali", "Clinic", "Srinivas", "12 August", "11:00 AM"],
        event_key="reschedule:background-voice",
        background_delivery=True,
    ) is True
    await asyncio.wait_for(entered.wait(), timeout=1)

    # enqueue returned while the provider is still blocked; voice can respond.
    release.set()
    for _ in range(20):
        await asyncio.sleep(0.01)
        db.expire_all()
        row = (
            await db.execute(
                select(WhatsAppDelivery).where(
                    WhatsAppDelivery.event_key == "reschedule:background-voice"
                )
            )
        ).scalar_one()
        if row.status == "sent":
            break
    assert row.status == "sent"


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


async def test_disconnect_during_failed_send_cancels_instead_of_retrying(
    db, monkeypatch
):
    branch = await _branch(db)
    sends = 0

    monkeypatch.setattr(wa_service, "wa_enabled", lambda *a, **k: True)

    async def disconnect_then_fail(*args, **kwargs):
        nonlocal sends
        sends += 1
        async with wa_delivery._db_module.AsyncSessionLocal() as other_db:
            current = await other_db.get(Branch, branch.id)
            await disconnect_branch(other_db, current)
            await other_db.commit()
        return False

    monkeypatch.setattr(meta_service, "send_purpose", disconnect_then_fail)
    assert await wa_delivery.enqueue(
        branch.id,
        "+919876500004",
        "booking_confirm",
        ["Anjali", "Clinic", "Srinivas", "12 August", "10:30 AM"],
        event_key="booking:disconnect-race",
    ) is False

    db.expire_all()
    task = (await db.execute(select(WhatsAppDelivery))).scalar_one()
    assert sends == 1
    assert task.status == "cancelled"
    assert task.attempts == 0

    # Even if a stale worker sees this row later, a cancelled task is terminal.
    assert await wa_delivery.deliver(task.id) is False
    assert sends == 1
