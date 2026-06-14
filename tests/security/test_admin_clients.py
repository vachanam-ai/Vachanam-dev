"""Admin clients/owners endpoints — access control + data shape.

super_admin sees the registered-clinics roll-up; org_admin and unauthenticated
callers are rejected (no clinic commercial data leaks downward).
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings
from backend.models.schema import Organization


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


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest.mark.asyncio
async def test_clients_requires_admin(client):
    # org_admin (is_admin False) -> 403
    r = await client.get(
        "/admin/clients", headers={"Authorization": f"Bearer {_jwt('org_admin', False)}"}
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_clients_unauthenticated_401(client):
    r = await client.get("/admin/clients")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_clients_lists_registered_orgs(client, db):
    org = Organization(
        name="Roll-up Test Clinic",
        owner_phone="+918096007554",
        owner_email=f"rollup-{uuid.uuid4().hex[:6]}@example.com",
        plan="clinic",
        status="trial",
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=10),
    )
    db.add(org)
    await db.commit()

    r = await client.get(
        "/admin/clients", headers={"Authorization": f"Bearer {_jwt()}"}
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_clients"] >= 1
    assert data["trialing"] >= 1
    names = [c["name"] for c in data["clients"]]
    assert "Roll-up Test Clinic" in names
    row = next(c for c in data["clients"] if c["name"] == "Roll-up Test Clinic")
    assert row["plan"] == "clinic"
    assert row["days_left"] is not None and 0 <= row["days_left"] <= 10
    # No patient PII fields present on the row
    assert "patient" not in str(row).lower()


@pytest.mark.asyncio
async def test_add_owner_weak_password_rejected(client, db):
    """iter1 #16: creating a super_admin with a weak password must be rejected by
    the shared validate_password (all-numeric here), not the old bare len>=8 check.
    """
    email = f"newowner-{uuid.uuid4().hex[:6]}@vachanam.in"
    r = await client.post(
        "/admin/owners",
        headers={"Authorization": f"Bearer {_jwt()}"},
        json={"email": email, "name": "Weak Owner", "password": "12345678"},
    )
    assert r.status_code == 422, r.text


@pytest.mark.asyncio
async def test_add_owner_strong_password_accepted(client, db):
    """A password that clears validate_password creates the owner (201)."""
    email = f"newowner-{uuid.uuid4().hex[:6]}@vachanam.in"
    r = await client.post(
        "/admin/owners",
        headers={"Authorization": f"Bearer {_jwt()}"},
        json={"email": email, "name": "Strong Owner", "password": "Str0ngPass99"},
    )
    assert r.status_code == 201, r.text
