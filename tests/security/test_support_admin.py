"""Phase 2/3 support: RBAC (support vs super_admin vs clinic), cross-org inbox,
RULE 1 PII lockout for support staff, reply/status/csat/contact/staff flows.
Resend is off in tests (resend_api_key empty) so email sends are no-ops.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import select

from backend.config import settings

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app
    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _jwt(role, org_id=None, is_admin=False):
    now = datetime.now(timezone.utc)
    return jwt.encode({"sub": str(uuid.uuid4()), "email": f"{role}@t.com", "role": role,
                       "org_id": str(org_id) if org_id else None, "branch_ids": [],
                       "is_admin": is_admin, "iat": int(now.timestamp()),
                       "exp": int((now + timedelta(hours=8)).timestamp()),
                       "jti": str(uuid.uuid4())}, settings.jwt_secret, algorithm="HS256")


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _org(db, tag="C"):
    from backend.models.schema import Organization
    o = Organization(name=tag, owner_phone="", owner_email=f"{uuid.uuid4().hex}@t.com",
                     plan="clinic", status="active")
    db.add(o)
    await db.flush()
    return o


async def _ticket(db, org, status="open", branch=None):
    from backend.models.schema import SupportMessage, SupportTicket
    t = SupportTicket(org_id=org.id if org else None, email="o@t.com", subject="help me",
                      category="other", status=status, priority="normal",
                      source="in_app", sla_due_at=datetime.now(timezone.utc))
    db.add(t)
    await db.flush()
    db.add(SupportMessage(ticket_id=t.id, sender="user", body="body text"))
    await db.commit()
    return t


# ── RBAC on the admin dashboard ──────────────────────────────────────────────

async def test_org_admin_denied_admin_dashboard(client, db):
    org = await _org(db)
    await db.commit()
    r = await client.get("/support/admin/tickets",
                         headers=_auth(_jwt("org_admin", org.id)))
    assert r.status_code == 403


async def test_support_staff_sees_cross_org_excluding_ai_resolved(client, db):
    a = await _org(db, "A")
    b = await _org(db, "B")
    await _ticket(db, a, status="open")
    await _ticket(db, b, status="ai_resolved")
    r = await client.get("/support/admin/tickets", headers=_auth(_jwt("support")))
    assert r.status_code == 200
    statuses = [row["status"] for row in r.json()]
    assert "open" in statuses and "ai_resolved" not in statuses  # default hides answered


# ── RULE 1: support staff are PII-locked (super_admin-lite) ──────────────────

async def test_support_role_blocked_from_patient_pii(client, db):
    org = await _org(db)
    await db.commit()
    # /patients/* is guarded by forbid_admin, which now also blocks 'support'
    r = await client.get(f"/patients/branches/{uuid.uuid4()}/patients",
                         headers=_auth(_jwt("support")))
    assert r.status_code == 403


# ── Staff provisioning (super_admin only) ────────────────────────────────────

async def test_super_admin_manages_staff_but_support_cannot(client, db):
    from backend.models.schema import User
    sa = _jwt("super_admin", is_admin=True)
    r = await client.post("/support/admin/staff", headers=_auth(sa),
                          json={"email": "agent1@vachanam.in", "name": "Agent One",
                                "password": "Str0ng!pass"})
    assert r.status_code == 200
    sid = r.json()["id"]
    row = (await db.execute(select(User).where(User.id == uuid.UUID(sid)))).scalar_one()
    assert row.role == "support" and row.is_admin is False and row.org_id is None
    # support staff CANNOT create more staff (require_admin → is_admin False)
    r = await client.post("/support/admin/staff", headers=_auth(_jwt("support")),
                          json={"email": "x@y.com", "name": "X", "password": "Str0ng!pass"})
    assert r.status_code == 403
    # super_admin lists + deletes
    r = await client.get("/support/admin/staff", headers=_auth(sa))
    assert any(u["id"] == sid for u in r.json())
    r = await client.delete(f"/support/admin/staff/{sid}", headers=_auth(sa))
    assert r.status_code == 200


async def test_support_lead_can_manage_staff(client, db):
    """The designated support lead (support user whose email == support_email)
    can add/remove staff; a regular support user cannot."""
    from datetime import datetime, timedelta, timezone
    from backend.config import settings

    def _lead_jwt():
        now = datetime.now(timezone.utc)
        return jwt.encode({"sub": str(uuid.uuid4()), "email": settings.support_email,
                           "role": "support", "org_id": None, "branch_ids": [],
                           "is_admin": False, "iat": int(now.timestamp()),
                           "exp": int((now + timedelta(hours=8)).timestamp()),
                           "jti": str(uuid.uuid4())}, settings.jwt_secret, algorithm="HS256")

    lead = _lead_jwt()
    r = await client.get("/support/admin/staff", headers=_auth(lead))
    assert r.status_code == 200  # lead may manage the team
    r = await client.post("/support/admin/staff", headers=_auth(lead),
                          json={"email": "agent2@vachanam.in", "name": "Agent Two",
                                "password": "Str0ng!pass"})
    assert r.status_code == 200
    # a regular support user (different email) still cannot
    r = await client.get("/support/admin/staff", headers=_auth(_jwt("support")))
    assert r.status_code == 403


# ── Staff reply + status transitions ─────────────────────────────────────────

async def test_staff_reply_sets_pending_and_first_response(client, db):
    from backend.models.schema import SupportTicket
    org = await _org(db)
    t = await _ticket(db, org, status="open")
    r = await client.post(f"/support/admin/tickets/{t.id}/reply",
                          headers=_auth(_jwt("support")), json={"body": "on it"})
    assert r.status_code == 200 and r.json()["status"] == "pending"
    row = (await db.execute(select(SupportTicket).where(SupportTicket.id == t.id))).scalar_one()
    assert row.first_responded_at is not None


async def test_patch_resolve_stamps_resolved_at(client, db):
    from backend.models.schema import SupportTicket
    org = await _org(db)
    t = await _ticket(db, org, status="pending")
    r = await client.patch(f"/support/admin/tickets/{t.id}",
                           headers=_auth(_jwt("support")), json={"status": "resolved"})
    assert r.status_code == 200
    assert r.json()["status"] == "resolved"
    # Read in a FRESH session — the fixture session holds an open snapshot that
    # predates the handler's separate-session commit.
    import backend.database as _dbm
    async with _dbm.AsyncSessionLocal() as s2:
        row = (await s2.execute(select(SupportTicket).where(SupportTicket.id == t.id))).scalar_one()
        assert row.status == "resolved" and row.resolved_at is not None


# ── Clinic user: reply reopens, CSAT only on resolved ────────────────────────

async def test_user_reply_reopens_and_csat_gate(client, db):
    from backend.models.schema import SupportTicket
    org = await _org(db)
    t = await _ticket(db, org, status="resolved")
    tok = _jwt("org_admin", org.id)
    # CSAT allowed on resolved
    r = await client.post(f"/support/tickets/{t.id}/csat", headers=_auth(tok),
                          json={"score": 5})
    assert r.status_code == 200
    # a user reply reopens the ticket
    r = await client.post(f"/support/tickets/{t.id}/messages", headers=_auth(tok),
                          json={"body": "actually still broken"})
    assert r.status_code == 200 and r.json()["status"] == "open"
    # CSAT now rejected (no longer resolved)
    r = await client.post(f"/support/tickets/{t.id}/csat", headers=_auth(tok),
                          json={"score": 1})
    assert r.status_code == 409


# ── Public contact form → a lead ticket (org_id NULL) ────────────────────────

async def test_public_contact_creates_lead_ticket(client, db):
    from backend.models.schema import SupportTicket
    r = await client.post("/support/contact", json={
        "email": "lead@clinic.com", "name": "Dr Lead", "subject": "demo please",
        "body": "want a demo for my dental clinic", "category": "sales_demo"})
    assert r.status_code == 200
    tid = uuid.UUID(r.json()["ticket_id"])
    row = (await db.execute(select(SupportTicket).where(SupportTicket.id == tid))).scalar_one()
    assert row.org_id is None and row.category == "sales_demo" and row.source == "public_form"


async def test_macros_available_to_staff(client):
    r = await client.get("/support/admin/macros", headers=_auth(_jwt("support")))
    assert r.status_code == 200 and len(r.json()) >= 1
