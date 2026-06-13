"""Payments billing: auth-gated orders + webhook-driven activation (TD-019/025).

- create-order requires a clinic owner (no anon, no super_admin); amount is the
  plan price, server-derived.
- the Razorpay webhook is the authoritative activation: a valid signature over
  the raw body flips the org to active and writes a paid BillingCycle, idempotent
  on razorpay_payment_id (webhook redeliveries don't double-bill).
"""
import hashlib
import hmac
import json
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt
from sqlalchemy import func, select

from backend.config import settings
from backend.models.schema import BillingCycle, Branch, Organization

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _jwt(role, org_id=None, branch_id=None, is_admin=False):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": f"{role}@pay.test", "role": role,
            "org_id": org_id, "branch_ids": [branch_id] if branch_id else [],
            "is_admin": is_admin, "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def org(db):
    o = Organization(
        name="Pay Org", owner_phone="+919000999001",
        owner_email=f"pay-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="trial",
    )
    db.add(o)
    await db.commit()
    return o


async def test_create_order_requires_auth(client):
    r = await client.post("/api/create-order", json={"plan": "clinic"})
    assert r.status_code == 401, r.text


async def test_create_order_super_admin_forbidden(client):
    r = await client.post(
        "/api/create-order", headers=_auth(_jwt("super_admin", is_admin=True)),
        json={"plan": "clinic"},
    )
    assert r.status_code == 403, r.text


async def test_create_order_invalid_plan_422(client, org):
    r = await client.post(
        "/api/create-order", headers=_auth(_jwt("org_admin", org_id=str(org.id))),
        json={"plan": "platinum"},
    )
    assert r.status_code == 422, r.text


def _signed(secret: str, body: dict):
    raw = json.dumps(body).encode()
    sig = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return raw, sig


async def test_webhook_bad_signature_400(client, monkeypatch):
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec_test", raising=False)
    r = await client.post(
        "/api/razorpay-webhook", content=b'{"event":"order.paid"}',
        headers={"X-Razorpay-Signature": "deadbeef", "content-type": "application/json"},
    )
    assert r.status_code == 400, r.text


async def test_webhook_activates_subscription(client, db, org, monkeypatch):
    secret = "whsec_activate"
    monkeypatch.setattr(settings, "razorpay_webhook_secret", secret, raising=False)
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    body = {
        "event": "order.paid",
        "payload": {
            "order": {"entity": {"id": f"order_{uuid.uuid4().hex[:10]}",
                                 "notes": {"org_id": str(org.id), "plan": "clinic"}}},
            "payment": {"entity": {"id": payment_id}},
        },
    }
    raw, sig = _signed(secret, body)
    r = await client.post(
        "/api/razorpay-webhook", content=raw,
        headers={"X-Razorpay-Signature": sig, "content-type": "application/json"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "activated"

    oid = org.id  # capture before expire (avoids a sync lazy-load on the async session)
    db.expire_all()
    fresh = (
        await db.execute(select(Organization).where(Organization.id == oid))
    ).scalar_one()
    assert fresh.status == "active"
    assert fresh.subscription_started_at is not None

    bc = (
        await db.execute(
            select(BillingCycle).where(BillingCycle.razorpay_payment_id == payment_id)
        )
    ).scalar_one()
    assert bc.status == "paid"
    assert bc.base_amount == 7999  # clinic plan price


async def test_webhook_idempotent_on_redelivery(client, db, org, monkeypatch):
    secret = "whsec_idem"
    monkeypatch.setattr(settings, "razorpay_webhook_secret", secret, raising=False)
    payment_id = f"pay_{uuid.uuid4().hex[:12]}"
    body = {
        "event": "payment.captured",
        "payload": {
            "order": {"entity": {"id": "order_x",
                                 "notes": {"org_id": str(org.id), "plan": "solo"}}},
            "payment": {"entity": {"id": payment_id, "notes": {}}},
        },
    }
    raw, sig = _signed(secret, body)
    h = {"X-Razorpay-Signature": sig, "content-type": "application/json"}

    r1 = await client.post("/api/razorpay-webhook", content=raw, headers=h)
    r2 = await client.post("/api/razorpay-webhook", content=raw, headers=h)  # redelivery
    assert r1.json()["status"] == "activated"
    assert r2.json()["status"] == "already_processed"

    count = (
        await db.execute(
            select(func.count()).select_from(BillingCycle).where(
                BillingCycle.razorpay_payment_id == payment_id
            )
        )
    ).scalar_one()
    assert count == 1  # exactly one paid cycle despite two deliveries
