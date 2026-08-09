"""Razorpay recurring mandates: create, verify, webhook, and idempotency."""
import hashlib
import hmac
import json
import uuid
from datetime import date, datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio
from sqlalchemy import func, select

from backend.config import settings
from backend.models.schema import Branch, BillingCycle, Organization, RazorpayPlanMap
from backend.routers import payments
from backend.services.billing_math import subscription_order_breakdown

pytestmark = pytest.mark.asyncio


def _jwt(org_id):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "owner@autopay.test",
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


def _auth(org_id):
    return {"Authorization": f"Bearer {_jwt(org_id)}"}


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 321))
    async with httpx.AsyncClient(
        transport=transport, base_url="http://testserver"
    ) as ac:
        yield ac


@pytest_asyncio.fixture
async def org(db):
    value = Organization(
        name="Autopay Clinic",
        owner_phone="+919876500099",
        owner_email=f"autopay-{uuid.uuid4().hex[:8]}@test.com",
        plan="clinic",
        status="trial",
    )
    db.add(value)
    await db.commit()
    return value


class _Plans:
    def __init__(self, root):
        self.root = root

    def create(self, payload):
        self.root.plan_payloads.append(payload)
        return {"id": "plan_dynamic_1", **payload}


class _Subscriptions:
    def __init__(self, root):
        self.root = root

    def create(self, payload):
        self.root.subscription_payloads.append(payload)
        self.root.notes = payload["notes"]
        return {"id": "sub_autopay_1", "status": "created"}

    def fetch(self, subscription_id):
        return {
            "id": subscription_id,
            "status": self.root.fetch_status,
            "customer_id": "cust_1",
            "notes": self.root.notes,
        }

    def cancel(self, subscription_id, payload):
        self.root.cancel_payloads.append((subscription_id, payload))
        return {"id": subscription_id, "status": "active"}

    def cancel_scheduled_changes(self, subscription_id, payload=None):
        self.root.cancelled_changes.append(subscription_id)
        return {"id": subscription_id}

    def edit(self, subscription_id, payload):
        self.root.edit_payloads.append((subscription_id, payload))
        return {"id": subscription_id}


class FakeRazorpay:
    def __init__(self):
        self.plan_payloads = []
        self.subscription_payloads = []
        self.cancel_payloads = []
        self.cancelled_changes = []
        self.edit_payloads = []
        self.fetch_status = "authenticated"
        self.notes = {}
        self.plan = _Plans(self)
        self.subscription = _Subscriptions(self)


async def _cycle(db, org, *, days=10):
    row = BillingCycle(
        org_id=org.id,
        cycle_start=date.today() - timedelta(days=20),
        cycle_end=date.today() + timedelta(days=days),
        plan=org.plan,
        base_amount=9999,
        included_minutes=1500,
        minutes_used=0,
        overage_minutes=0,
        overage_rate=5,
        overage_amount=0,
        status="paid",
        razorpay_payment_id=f"pay_{uuid.uuid4().hex[:12]}",
    )
    db.add(row)
    await db.commit()
    return row


async def test_create_and_verify_real_autopay_mandate(
    client, db, org, monkeypatch
):
    org_id = org.id
    provider = FakeRazorpay()
    monkeypatch.setattr(payments, "_get_client", lambda: provider)
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_autopay")
    monkeypatch.setattr(settings, "razorpay_key_secret", "autopay-secret")

    response = await client.post(
        "/api/create-subscription",
        headers=_auth(org_id),
        json={"plan": "clinic"},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["subscription_id"] == "sub_autopay_1"
    assert provider.plan_payloads[0]["period"] == "monthly"
    assert provider.plan_payloads[0]["item"]["amount"] == body["amount"]
    assert provider.subscription_payloads[0]["total_count"] == 120
    assert provider.subscription_payloads[0]["customer_notify"] is True

    signature = hmac.new(
        b"autopay-secret",
        b"pay_auth_1|sub_autopay_1",
        hashlib.sha256,
    ).hexdigest()
    verified = await client.post(
        "/api/verify-subscription",
        headers=_auth(org_id),
        json={
            "razorpay_subscription_id": "sub_autopay_1",
            "razorpay_payment_id": "pay_auth_1",
            "razorpay_signature": signature,
        },
    )
    assert verified.status_code == 200, verified.text

    db.expire_all()
    fresh = await db.get(Organization, org_id)
    assert fresh.razorpay_subscription_id == "sub_autopay_1"
    assert fresh.razorpay_subscription_status == "authenticated"
    assert fresh.razorpay_customer_id == "cust_1"
    mapped = (await db.execute(select(RazorpayPlanMap))).scalar_one()
    assert mapped.amount_paise == body["amount"]

    plan = await client.get("/api/plan", headers=_auth(org_id))
    assert plan.json()["autopay_enabled"] is True


async def test_subscription_charged_webhook_is_idempotent(
    client, db, org, monkeypatch
):
    secret = "autopay-webhook-secret"
    monkeypatch.setattr(settings, "razorpay_webhook_secret", secret)
    org.razorpay_subscription_id = "sub_charged_1"
    org.razorpay_subscription_status = "authenticated"
    await db.commit()
    payment_id = "pay_recurring_1"
    body = {
        "event": "subscription.charged",
        "payload": {
            "subscription": {"entity": {
                "id": "sub_charged_1",
                "status": "active",
                "customer_id": "cust_recurring",
                "notes": {"org_id": str(org.id), "plan": "clinic"},
            }},
            "payment": {"entity": {"id": payment_id}},
        },
    }
    raw = json.dumps(body).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    headers = {
        "X-Razorpay-Signature": signature,
        "content-type": "application/json",
    }
    first = await client.post(
        "/api/razorpay-webhook", content=raw, headers=headers
    )
    second = await client.post(
        "/api/razorpay-webhook", content=raw, headers=headers
    )
    assert first.json()["status"] == "activated"
    assert second.json()["status"] == "already_processed"
    count = (
        await db.execute(
            select(func.count()).select_from(BillingCycle).where(
                BillingCycle.razorpay_payment_id == payment_id
            )
        )
    ).scalar_one()
    assert count == 1


async def test_plan_change_never_repeats_current_overage(
    client, db, org, monkeypatch
):
    provider = FakeRazorpay()
    monkeypatch.setattr(payments, "_get_client", lambda: provider)
    org.status = "active"
    org.razorpay_subscription_id = "sub_change_1"
    org.razorpay_subscription_status = "active"
    await db.commit()
    await _cycle(db, org)

    response = await client.post(
        "/api/plan-change",
        headers=_auth(org.id),
        json={"plan": "multi"},
    )
    assert response.status_code == 200, response.text
    expected = subscription_order_breakdown(
        "multi", 0, 0, subscription_started_at=org.subscription_started_at
    )["amount_paise"]
    assert provider.plan_payloads[-1]["item"]["amount"] == expected
    assert provider.edit_payloads[-1][1]["schedule_change_at"] == "cycle_end"


async def test_paid_whatsapp_addon_updates_existing_mandate_before_entitlement(
    db, org, monkeypatch
):
    provider = FakeRazorpay()
    monkeypatch.setattr(payments, "_get_client", lambda: provider)
    org.plan = "solo"
    org.status = "active"
    org.razorpay_subscription_id = "sub_addon_1"
    org.razorpay_subscription_status = "active"
    branch = Branch(
        org_id=org.id,
        name="Autopay Add-on Branch",
        status="active",
        whatsapp_number="+919876500088",
    )
    db.add(branch)
    await db.commit()

    result = await payments._enable_whatsapp_addon(
        db,
        {"org_id": str(org.id), "branch_id": str(branch.id)},
        "pay_addon_autopay_1",
    )

    expected = subscription_order_breakdown(
        "solo",
        0,
        0,
        subscription_started_at=org.subscription_started_at,
        whatsapp_addon=True,
    )["amount_paise"]
    assert result == "addon_enabled"
    assert provider.plan_payloads[-1]["item"]["amount"] == expected
    assert provider.edit_payloads[-1] == (
        "sub_addon_1",
        {
            "plan_id": "plan_dynamic_1",
            "schedule_change_at": "cycle_end",
            "customer_notify": True,
        },
    )
    await db.refresh(branch)
    assert branch.whatsapp_addon is True


async def test_addon_provider_rejection_does_not_grant_entitlement(
    db, org, monkeypatch
):
    provider = FakeRazorpay()
    org.plan = "solo"
    org.status = "active"
    org.razorpay_subscription_id = "sub_addon_reject"
    org.razorpay_subscription_status = "active"
    branch = Branch(
        org_id=org.id,
        name="Rejected Add-on Branch",
        status="active",
        whatsapp_number="+919876500077",
    )
    db.add(branch)
    await db.commit()

    def reject_edit(_subscription_id, _payload):
        raise RuntimeError("provider rejected update")

    provider.subscription.edit = reject_edit
    monkeypatch.setattr(payments, "_get_client", lambda: provider)

    with pytest.raises(RuntimeError, match="provider rejected"):
        await payments._enable_whatsapp_addon(
            db,
            {"org_id": str(org.id), "branch_id": str(branch.id)},
            "pay_addon_reject_1",
        )

    await db.refresh(branch)
    assert branch.whatsapp_addon is False


async def test_autopay_cancellation_cannot_be_falsely_undone(
    client, db, org, monkeypatch
):
    provider = FakeRazorpay()
    monkeypatch.setattr(payments, "_get_client", lambda: provider)
    org.status = "active"
    org.razorpay_subscription_id = "sub_cancel_1"
    org.razorpay_subscription_status = "active"
    await db.commit()
    cycle = await _cycle(db, org)

    scheduled = await client.post(
        "/api/plan-cancel", headers=_auth(org.id), json={"cancel": True}
    )
    assert scheduled.status_code == 200, scheduled.text
    assert scheduled.json()["cancellation_effective"] == cycle.cycle_end.isoformat()
    assert provider.cancel_payloads == [
        ("sub_cancel_1", {"cancel_at_cycle_end": True})
    ]

    undo = await client.post(
        "/api/plan-cancel", headers=_auth(org.id), json={"cancel": False}
    )
    assert undo.status_code == 409
    assert "does not reactivate" not in undo.text.lower()
    assert "already scheduled" in undo.text.lower()


async def test_recurring_charge_uses_due_pending_plan(
    client, db, org, monkeypatch
):
    org_id = org.id
    secret = "autopay-pending-secret"
    monkeypatch.setattr(settings, "razorpay_webhook_secret", secret)
    org.status = "active"
    org.plan = "clinic"
    org.pending_plan = "multi"
    org.pending_plan_effective = date.today()
    org.razorpay_subscription_id = "sub_pending_1"
    org.razorpay_subscription_status = "active"
    await db.commit()
    body = {
        "event": "subscription.charged",
        "payload": {
            "subscription": {"entity": {
                "id": "sub_pending_1",
                "status": "active",
                "notes": {"org_id": str(org_id), "plan": "clinic"},
            }},
            "payment": {"entity": {"id": "pay_pending_plan"}},
        },
    }
    raw = json.dumps(body).encode()
    signature = hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    response = await client.post(
        "/api/razorpay-webhook",
        content=raw,
        headers={
            "X-Razorpay-Signature": signature,
            "content-type": "application/json",
        },
    )
    assert response.status_code == 200
    db.expire_all()
    fresh = await db.get(Organization, org_id)
    assert fresh.plan == "multi"
    assert fresh.pending_plan is None
