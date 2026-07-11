"""Support tables: ticket + threaded messages, org-scoped (NULL org = public lead)."""
import uuid

import pytest

pytestmark = pytest.mark.asyncio


async def test_ticket_and_message_roundtrip(db):
    from backend.models.schema import Organization, SupportMessage, SupportTicket

    org = Organization(
        name="C", owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
        plan="clinic", status="trial",
    )
    db.add(org)
    await db.flush()

    t = SupportTicket(
        org_id=org.id, email="o@t.com", subject="help",
        category="technical", status="open", priority="normal", source="in_app",
    )
    db.add(t)
    await db.flush()
    db.add(SupportMessage(ticket_id=t.id, sender="user", body="my call failed"))
    await db.commit()
    await db.refresh(t)
    assert t.status == "open"
    assert t.org_id == org.id


async def test_public_ticket_allows_null_org(db):
    from backend.models.schema import SupportTicket

    t = SupportTicket(
        org_id=None, email="lead@x.com", name="Lead", subject="demo",
        category="sales_demo", status="open", priority="normal", source="public_form",
    )
    db.add(t)
    await db.commit()
    await db.refresh(t)
    assert t.org_id is None
