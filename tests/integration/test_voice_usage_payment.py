"""Closed-cycle voice usage has one exact, idempotent payment."""
import hashlib
import hmac
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio

from backend.config import settings
from backend.models.schema import BillingCycle, Organization
from backend.routers import payments

pytestmark = pytest.mark.asyncio


def _auth(org_id: uuid.UUID) -> dict[str, str]:
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "owner@usage.test",
            "role": "org_admin",
            "org_id": str(org_id),
            "branch_ids": [],
            "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 901))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _due_cycle(db, *, amount: int = 240) -> tuple[Organization, BillingCycle]:
    org = Organization(
        name=f"Usage Clinic {uuid.uuid4().hex[:6]}",
        owner_phone="",
        owner_email=f"usage-{uuid.uuid4().hex[:8]}@test.com",
        plan="solo",
        status="active",
    )
    db.add(org)
    await db.flush()
    end = date.today() - timedelta(days=1)
    cycle = BillingCycle(
        org_id=org.id,
        cycle_start=end - timedelta(days=30),
        cycle_end=end,
        plan="solo",
        base_amount=1999,
        included_minutes=0,
        minutes_used=40,
        overage_minutes=40,
        overage_rate=6,
        overage_amount=amount,
        status="invoiced",
        razorpay_payment_id=f"pay_base_{uuid.uuid4().hex[:10]}",
    )
    db.add(cycle)
    await db.commit()
    return org, cycle


class _Orders:
    def __init__(self):
        self.created = []
        self.orders = {}

    def create(self, payload):
        self.created.append(payload)
        order = {"id": f"order_usage_{len(self.created)}", **payload}
        self.orders[order["id"]] = order
        return order

    def fetch(self, order_id):
        return self.orders[order_id]


class _Provider:
    def __init__(self):
        self.order = _Orders()


async def test_one_cycle_reuses_one_server_priced_order(client, db, monkeypatch):
    org, cycle = await _due_cycle(db)
    provider = _Provider()
    monkeypatch.setattr(payments, "_get_client", lambda: provider)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_usage")

    first = await client.post(
        f"/api/billing/cycles/{cycle.id}/usage-order", headers=_auth(org.id)
    )
    second = await client.post(
        f"/api/billing/cycles/{cycle.id}/usage-order", headers=_auth(org.id)
    )

    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["amount"] == 24_000
    assert len(provider.order.created) == 1
    await db.refresh(cycle)
    assert cycle.overage_order_id == first.json()["order_id"]
    assert cycle.overage_order_amount_paise == 24_000


async def test_other_clinic_cannot_open_or_discover_usage_order(client, db, monkeypatch):
    _owner, cycle = await _due_cycle(db)
    stranger, _their_cycle = await _due_cycle(db, amount=60)
    provider = _Provider()
    monkeypatch.setattr(payments, "_get_client", lambda: provider)

    response = await client.post(
        f"/api/billing/cycles/{cycle.id}/usage-order", headers=_auth(stranger.id)
    )

    assert response.status_code == 404
    assert not provider.order.created


async def test_usage_checkout_verifies_and_settles_once(client, db, monkeypatch):
    org, cycle = await _due_cycle(db)
    provider = _Provider()
    monkeypatch.setattr(payments, "_get_client", lambda: provider)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_usage")
    monkeypatch.setattr(settings, "razorpay_key_secret", "usage-secret")

    created = await client.post(
        f"/api/billing/cycles/{cycle.id}/usage-order", headers=_auth(org.id)
    )
    order_id = created.json()["order_id"]
    payment_id = "pay_usage_exactly_once"
    signature = hmac.new(
        b"usage-secret", f"{order_id}|{payment_id}".encode(), hashlib.sha256
    ).hexdigest()
    payload = {
        "razorpay_order_id": order_id,
        "razorpay_payment_id": payment_id,
        "razorpay_signature": signature,
    }

    first = await client.post("/api/verify-payment", json=payload)
    second = await client.post("/api/verify-payment", json=payload)

    assert first.status_code == second.status_code == 200
    await db.refresh(cycle)
    assert cycle.status == "paid"
    assert cycle.overage_payment_id == payment_id


async def test_settlement_rejects_a_different_order_for_same_cycle(db):
    _org, cycle = await _due_cycle(db)
    cycle.overage_order_id = "order_expected"
    cycle.overage_order_amount_paise = 24_000
    await db.commit()
    notes = {
        "org_id": str(cycle.org_id),
        "cycle_id": str(cycle.id),
        "overage_amount": "240",
    }

    status = await payments._settle_voice_usage_payment(
        db, notes, "pay_wrong_order", order_id="order_other"
    )

    assert status == "order_mismatch"
    await db.refresh(cycle)
    assert cycle.status == "invoiced"
    assert cycle.overage_payment_id is None
