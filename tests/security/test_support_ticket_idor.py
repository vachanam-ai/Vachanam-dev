"""Ticket reads are org-scoped: clinic B can never see clinic A's ticket/thread."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt

from backend.config import settings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _tok(org_id):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(uuid.uuid4()), "email": "o@t.com", "role": "org_admin",
                       "org_id": str(org_id), "branch_ids": [], "is_admin": False,
                       "iat": int(now.timestamp()),
                       "exp": int((now + timedelta(hours=8)).timestamp()),
                       "jti": str(uuid.uuid4())}, settings.jwt_secret, algorithm="HS256")


async def _mk(db, tag):
    from backend.models.schema import Organization, SupportMessage, SupportTicket
    org = Organization(name=tag, owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    t = SupportTicket(org_id=org.id, email="o@t.com", subject="s", category="other",
                      status="open", priority="normal", source="in_app")
    db.add(t)
    await db.flush()
    db.add(SupportMessage(ticket_id=t.id, sender="user", body="secret body A"))
    await db.commit()
    return str(org.id), str(t.id)


async def test_clinic_cannot_read_another_clinics_ticket(client, db):
    a_org, a_ticket = await _mk(db, "A")
    b_org, _ = await _mk(db, "B")
    tokB = _tok(b_org)
    r = await client.get("/support/tickets", headers={"Authorization": f"Bearer {tokB}"})
    assert r.status_code == 200 and a_ticket not in r.text
    r = await client.get(f"/support/tickets/{a_ticket}", headers={"Authorization": f"Bearer {tokB}"})
    assert r.status_code == 404
    r = await client.get(f"/support/tickets/{a_ticket}/messages",
                         headers={"Authorization": f"Bearer {tokB}"})
    assert r.status_code == 404 and "secret body A" not in r.text


async def test_owner_reads_own_ticket_thread(client, db):
    org, ticket = await _mk(db, "own")
    tok = _tok(org)
    r = await client.get(f"/support/tickets/{ticket}/messages",
                         headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200 and "secret body A" in r.text
