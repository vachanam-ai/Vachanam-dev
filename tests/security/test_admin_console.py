"""Super-admin business console â€” access control, money math, org controls.

The console exposes commercial aggregates ONLY (DPDP: no patient data). The
controls (pause/resume, plan change, hard-block) mutate live orgs â€” they must
be super_admin-gated and actually persist.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import Branch, CallLog, Organization


def _jwt(role="super_admin", is_admin=True):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "email": f"admin-{uuid.uuid4().hex[:6]}@vachanam.in",
        "role": role,
        "org_id": None,
        "branch_ids": [],
        "is_admin": is_admin,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def _admin_headers():
    return {"Authorization": f"Bearer {_jwt()}"}

async def _fresh_org(org_uuid):
    """Read the org through a brand-new session — proves the router's commit
    actually reached the database (fixture session may hold stale state)."""
    import backend.database as _db_module

    async with _db_module.AsyncSessionLocal() as s:
        return (
            await s.execute(select(Organization).where(Organization.id == org_uuid))
        ).scalar_one()


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def biz_org(db):
    org = Organization(
        name=f"Console Clinic {uuid.uuid4().hex[:5]}",
        owner_phone="+918096007554",
        owner_email=f"console-{uuid.uuid4().hex[:6]}@example.com",
        plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="Console Branch",
        whatsapp_number=f"+9111{uuid.uuid4().int % 10**8:08d}",
        did_number=f"+9122{uuid.uuid4().int % 10**8:08d}",
        status="active",
    )
    db.add(branch)
    await db.flush()
    # 120 minutes of calls this month, 3 of them bookings
    now = datetime.now(timezone.utc)
    for i in range(6):
        db.add(
            CallLog(
                branch_id=branch.id,
                call_type="inbound",
                caller_last4="4428",
                answered=True,
                started_at=now - timedelta(hours=i + 1),
                duration_seconds=1200,  # 20 min each
                booking_made=i < 3,
            )
        )
    await db.commit()
    return {"org": org, "branch": branch}


@pytest.mark.asyncio
async def test_overview_requires_admin(client):
    r = await client.get(
        "/admin/overview", headers={"Authorization": f"Bearer {_jwt('org_admin', False)}"}
    )
    assert r.status_code == 403
    r = await client.get("/admin/overview")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_overview_money_and_usage_math(client, biz_org):
    r = await client.get("/admin/overview", headers=_admin_headers())
    assert r.status_code == 200, r.text
    data = r.json()
    row = next(c for c in data["clients"] if c["org_id"] == str(biz_org["org"].id))
    assert row["minutes_used"] == 120.0
    assert row["minutes_included"] == 1500  # clinic plan (repriced 2026-07-11)
    assert row["minutes_left"] == 1380.0  # 1500 - 120
    assert row["revenue_month"] == 9999  # active clinic within bucket
    assert row["expense_month"] == round(120 * 2.0 + 1000, 2)  # 1 DID
    assert row["profit_month"] == round(9999 - (120 * 2.0 + 1000), 2)
    assert row["calls_month"] == 6
    assert row["voice_bookings_month"] == 3
    assert row["approaching_limit"] is False
    assert row["blocked_now"] is False
    # totals include this org
    assert data["minutes_this_month"] >= 120.0
    assert data["revenue_month"] >= 9999
    # never any patient identifiers in the payload
    assert "patient" not in r.text.lower()

    # B22: the monthly trend's CURRENT-month expense must use the SAME
    # per-minute cost (₹2.0) as the per-clinic expense_month, not the stale
    # ₹1.49. Current month: 120 min + 1 DID = 120*2.0 + 1000 = 1240.
    from backend.services.billing_math import VARIABLE_COST_PER_MIN

    assert VARIABLE_COST_PER_MIN == 2.0
    cur = data["monthly"][-1]  # current month is the last point
    assert cur["expense"] == round(120 * VARIABLE_COST_PER_MIN + 1000, 2), cur


@pytest.mark.asyncio
async def test_pause_resume_persists(client, db, biz_org):
    org_id = str(biz_org["org"].id)
    r = await client.post(
        f"/admin/orgs/{org_id}/status", json={"status": "paused"}, headers=_admin_headers()
    )
    assert r.status_code == 200, r.text
    org = await _fresh_org(uuid.UUID(org_id))
    assert org.status == "paused"

    # paused org shows blocked_now on the overview
    r = await client.get("/admin/overview", headers=_admin_headers())
    row = next(c for c in r.json()["clients"] if c["org_id"] == org_id)
    assert row["blocked_now"] is True

    r = await client.post(
        f"/admin/orgs/{org_id}/status", json={"status": "active"}, headers=_admin_headers()
    )
    assert r.status_code == 200
    org = await _fresh_org(uuid.UUID(org_id))
    assert org.status == "active"


@pytest.mark.asyncio
async def test_plan_change_persists_and_validates(client, db, biz_org):
    org_id = str(biz_org["org"].id)
    r = await client.post(
        f"/admin/orgs/{org_id}/plan", json={"plan": "multi"}, headers=_admin_headers()
    )
    assert r.status_code == 200, r.text
    org = await _fresh_org(uuid.UUID(org_id))
    assert org.plan == "multi"

    # downgrade path too — "can't change clinic to solo" was reported 06-12
    r = await client.post(
        f"/admin/orgs/{org_id}/plan", json={"plan": "solo"}, headers=_admin_headers()
    )
    assert r.status_code == 200, r.text
    org = await _fresh_org(uuid.UUID(org_id))
    assert org.plan == "solo"

    r = await client.post(
        f"/admin/orgs/{org_id}/plan", json={"plan": "enterprise"}, headers=_admin_headers()
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_hard_block_toggle_persists(client, db, biz_org):
    org_id = str(biz_org["org"].id)
    r = await client.post(
        f"/admin/orgs/{org_id}/hard-block", json={"enabled": True}, headers=_admin_headers()
    )
    assert r.status_code == 200, r.text
    org = await _fresh_org(uuid.UUID(org_id))
    assert org.hard_block_on_exhaust is True


@pytest.mark.asyncio
async def test_org_controls_require_admin(client, biz_org):
    org_id = str(biz_org["org"].id)
    headers = {"Authorization": f"Bearer {_jwt('org_admin', False)}"}
    for path, body in [
        (f"/admin/orgs/{org_id}/status", {"status": "paused"}),
        (f"/admin/orgs/{org_id}/plan", {"plan": "solo"}),
        (f"/admin/orgs/{org_id}/hard-block", {"enabled": True}),
    ]:
        r = await client.post(path, json=body, headers=headers)
        assert r.status_code == 403, f"{path} not gated"


@pytest.mark.asyncio
async def test_org_controls_bad_org_404(client, db):
    # `db` ensures the schema exists for this function's event loop — the 404 path
    # still queries `organizations`, so without it the table may be absent
    # (depending on test ordering) and the endpoint 500s instead of 404ing.
    r = await client.post(
        f"/admin/orgs/{uuid.uuid4()}/status", json={"status": "paused"}, headers=_admin_headers()
    )
    assert r.status_code == 404
    r = await client.post(
        "/admin/orgs/not-a-uuid/status", json={"status": "paused"}, headers=_admin_headers()
    )
    assert r.status_code == 422
