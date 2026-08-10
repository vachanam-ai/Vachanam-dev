"""Disconnecting WhatsApp must take the stored conversations with it.

Vinay 2026-08-10: "when whatsapp disconnected, chats should also get lost
(conversations). right now it is static."

Before this, DELETE /branches/{id}/whatsapp cleared the credentials only, so
the Conversations page kept serving patient message text for a channel the
clinic had switched off — no purpose left to hold it under. The purge is
scoped to whatsapp_sessions: ClinicQuestion and PatientMessage record no
channel and are mostly voice-originated, so deleting them here would destroy
callbacks the clinic still owes.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import (
    Branch,
    Organization,
    WhatsAppDelivery,
    WhatsAppSession,
)

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _owner_jwt(org_id: str, branch_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "owner@wa-disconnect.test",
            "role": "org_admin", "org_id": org_id, "branch_ids": [branch_id],
            "is_admin": False, "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


async def _clinic(db):
    org = Organization(
        name="WA Disconnect Org", owner_phone="+919000700123",
        owner_email=f"wa-disc-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="WA Disconnect Branch",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", status="active",
        wa_waba_id=str(uuid.uuid4().int)[:15], wa_phone_number_id=str(uuid.uuid4().int)[:15],
        wa_verified_name="Disconnect Clinic", wa_status="connected",
    )
    db.add(branch)
    await db.commit()
    return org, branch


async def _session(db, branch_id, phone: str):
    row = WhatsAppSession(
        branch_id=branch_id, patient_phone=phone, state="CONFIRMED",
        session_data={"turns": [{"role": "patient", "text": "10:30 works", "at": "x"}]},
    )
    db.add(row)
    await db.commit()
    return row


async def _count(db, branch_id) -> int:
    rows = (
        await db.execute(
            select(WhatsAppSession).where(WhatsAppSession.branch_id == branch_id)
        )
    ).scalars().all()
    return len(rows)


async def test_disconnect_deletes_this_branch_conversations(client, db):
    org, branch = await _clinic(db)
    await _session(db, branch.id, "+919812345678")
    await _session(db, branch.id, "+919812345679")
    owner = _owner_jwt(str(org.id), str(branch.id))

    listed = await client.get(
        f"/branches/{branch.id}/whatsapp/chats", headers=_auth(owner)
    )
    assert listed.status_code == 200, listed.text
    assert len(listed.json()) == 2

    r = await client.delete(f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner))
    assert r.status_code == 200, r.text
    assert r.json()["conversations_deleted"] == 2

    # The page the clinic actually looks at must come back empty, not stale.
    after = await client.get(
        f"/branches/{branch.id}/whatsapp/chats", headers=_auth(owner)
    )
    assert after.status_code == 200, after.text
    assert after.json() == []
    assert await _count(db, branch.id) == 0


async def test_disconnect_never_touches_another_clinics_conversations(client, db):
    """RULE 1: the delete is branch-scoped, so one clinic switching WhatsApp
    off can never wipe a neighbour's threads."""
    org_a, branch_a = await _clinic(db)
    org_b, branch_b = await _clinic(db)
    await _session(db, branch_a.id, "+919812345678")
    await _session(db, branch_b.id, "+919812345678")  # same patient, both clinics

    owner_a = _owner_jwt(str(org_a.id), str(branch_a.id))
    r = await client.delete(f"/branches/{branch_a.id}/whatsapp/connect", headers=_auth(owner_a))
    assert r.status_code == 200, r.text
    assert r.json()["conversations_deleted"] == 1

    assert await _count(db, branch_a.id) == 0
    assert await _count(db, branch_b.id) == 1


async def test_disconnect_with_no_conversations_reports_zero(client, db):
    org, branch = await _clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.delete(f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner))
    assert r.status_code == 200, r.text
    assert r.json()["conversations_deleted"] == 0
    assert r.json()["wa_status"] == "disconnected"


async def test_credentials_and_conversations_clear_together(client, db):
    """Both halves in one transaction — never disconnected-but-still-storing."""
    org, branch = await _clinic(db)
    await _session(db, branch.id, "+919812345678")
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.delete(f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner))
    assert r.status_code == 200, r.text

    # The route committed on its own session. Re-read through this one, or we
    # assert against the pre-disconnect object still in the identity map.
    await db.refresh(branch)
    fresh = branch
    assert fresh.wa_waba_id is None
    assert fresh.wa_token_enc is None
    assert fresh.wa_phone_number_id is None
    assert fresh.wa_verified_name is None
    assert fresh.wa_status == "disconnected"
    assert fresh.wa_connected_at is None
    assert await _count(db, branch.id) == 0


async def test_disconnected_branch_never_serves_or_reveals_stale_rows(client, db):
    """The read boundary is fail-closed even if a stale row is restored from
    backup or written by an old process after the lifecycle purge."""
    org, branch = await _clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.delete(f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner))
    assert r.status_code == 200, r.text

    # Simulate data drift after the purge. Its existence must not be observable
    # through either the list or direct-thread endpoint while disconnected.
    await _session(db, branch.id, "+919812345678")
    listed = await client.get(
        f"/branches/{branch.id}/whatsapp/chats", headers=_auth(owner)
    )
    direct = await client.get(
        f"/branches/{branch.id}/whatsapp/chats/+919812345678",
        headers=_auth(owner),
    )
    assert listed.status_code == 200
    assert listed.json() == []
    assert direct.status_code == 404


async def test_disconnect_cancels_unsent_delivery_so_reconnect_cannot_send_it(client, db):
    org, branch = await _clinic(db)
    db.add(WhatsAppDelivery(
        branch_id=branch.id,
        event_key=f"booking:{uuid.uuid4()}",
        purpose="booking_confirm",
        recipient_phone="+919812345678",
        values_json=["patient", "doctor"],
        buttons_json=[],
        status="pending",
    ))
    await db.commit()
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.delete(f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner))
    assert r.status_code == 200, r.text
    assert r.json()["deliveries_cancelled"] == 1

    delivery = (await db.execute(
        select(WhatsAppDelivery).where(WhatsAppDelivery.branch_id == branch.id)
    )).scalar_one()
    assert delivery.status == "cancelled"
    assert delivery.last_error == "branch disconnected before delivery"
