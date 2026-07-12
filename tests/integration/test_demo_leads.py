"""#337: demo requests are phone-first LEADS, separated from support tickets.

- sales_demo contact: phone required (10-digit), email optional, priority high.
- Admin inbox (default) excludes sales_demo; leads=true returns ONLY sales_demo.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import SupportTicket


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _staff_headers():
    now = datetime.now(timezone.utc)
    tok = jwt.encode({"sub": str(uuid.uuid4()), "email": "s@t.com", "role": "support",
                      "org_id": None, "branch_ids": [], "is_admin": False,
                      "iat": int(now.timestamp()),
                      "exp": int((now + timedelta(hours=8)).timestamp()),
                      "jti": str(uuid.uuid4())}, settings.jwt_secret, algorithm="HS256")
    return {"Authorization": f"Bearer {tok}"}


@pytest.mark.asyncio
async def test_demo_contact_creates_high_priority_lead_without_email(client, db):
    r = await client.post("/support/contact", json={
        "name": "Ravi",
        "phone": "9866012345",
        "subject": "Demo request — Sunrise Dental",
        "body": "show telugu booking call",
        "category": "sales_demo",
    })
    assert r.status_code == 200, r.text
    tid = uuid.UUID(r.json()["ticket_id"])
    t = (await db.execute(select(SupportTicket).where(SupportTicket.id == tid))).scalar_one()
    assert t.priority == "high"
    assert t.phone == "9866012345"
    assert t.category == "sales_demo"
    assert t.org_id is None  # anonymous lead


@pytest.mark.asyncio
async def test_demo_contact_requires_10_digit_phone(client):
    r = await client.post("/support/contact", json={
        "name": "Ravi", "phone": "12345",
        "subject": "Demo", "body": "x", "category": "sales_demo",
    })
    assert r.status_code == 422
    r2 = await client.post("/support/contact", json={
        "name": "Ravi",
        "subject": "Demo", "body": "x", "category": "sales_demo",
    })
    assert r2.status_code == 422


@pytest.mark.asyncio
async def test_non_demo_contact_still_requires_email(client):
    r = await client.post("/support/contact", json={
        "name": "X", "subject": "Help", "body": "y", "category": "technical",
    })
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_admin_inbox_and_leads_are_separate(client, db):
    support_staff_headers = _staff_headers()
    # one lead + one ordinary ticket
    await client.post("/support/contact", json={
        "name": "Ravi", "phone": "9866099999",
        "subject": "Demo request — SmileCare", "body": "demo", "category": "sales_demo",
    })
    await client.post("/support/contact", json={
        "email": "owner@clinic.example", "subject": "Billing doubt",
        "body": "gst?", "category": "billing",
    })

    inbox = (await client.get("/support/admin/tickets", headers=support_staff_headers)).json()
    assert all(t["category"] != "sales_demo" for t in inbox)
    assert any(t["subject"] == "Billing doubt" for t in inbox)

    leads = (await client.get("/support/admin/tickets?leads=true",
                              headers=support_staff_headers)).json()
    assert leads and all(t["category"] == "sales_demo" for t in leads)
    lead = next(t for t in leads if t["subject"] == "Demo request — SmileCare")
    assert lead["phone"] == "9866099999"
    assert lead["priority"] == "high"
