"""Buying the WhatsApp add-on: who may, what it costs, and what it switches on.

Replaces the super-admin linking script — a clinic turns WhatsApp on itself now
(Vinay 2026-08-03), which is the only way this scales past the first clinic.

The security shape matters more than the happy path: the amount and the branch
are both server-derived, so a tampered request can neither buy a cheaper add-on
nor switch a paid feature on for somebody else's clinic (RULE 1).
"""
import hashlib
import hmac
import json
import uuid

import httpx
import pytest
import pytest_asyncio

from backend.models.schema import Branch, Organization
from backend.config import settings
from tests.integration.test_clinic_overview_lists import _auth, _owner


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _clinic(db, plan="solo", status="active"):
    org = Organization(
        name="WaBuyOrg", owner_phone="+919000700055",
        owner_email=f"wabuy-{uuid.uuid4().hex[:6]}@test.com",
        plan=plan, status=status,
    )
    db.add(org)
    await db.flush()
    br = Branch(
        org_id=org.id, name="WaBuyBranch", status="active",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}",
    )
    db.add(br)
    await db.commit()
    return org, br


@pytest.mark.asyncio
async def test_legacy_whatsapp_plan_cannot_buy_the_addon_again(client, db):
    org, br = await _clinic(db, plan="wa")
    r = await client.post(
        "/api/whatsapp-addon/order", headers=_auth(_owner(str(org.id), str(br.id)))
    )
    assert r.status_code == 409
    assert "already included" in r.text


@pytest.mark.asyncio
async def test_an_inactive_plan_must_activate_first(client, db):
    org, br = await _clinic(db, status="paused")
    r = await client.post(
        "/api/whatsapp-addon/order", headers=_auth(_owner(str(org.id), str(br.id)))
    )
    assert r.status_code == 409
    assert "Activate your plan first" in r.text


@pytest.mark.asyncio
async def test_only_a_clinic_owner_can_spend_money(client, db):
    """A receptionist must not be able to put ₹99 on the clinic's card."""
    import jwt as _jwt
    from datetime import datetime, timedelta, timezone

    from backend.config import settings

    org, br = await _clinic(db)
    now = datetime.now(timezone.utc)
    receptionist = _jwt.encode({
        "sub": str(uuid.uuid4()), "email": "r@t.test", "role": "receptionist",
        "org_id": str(org.id), "branch_ids": [str(br.id)], "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
    }, settings.jwt_secret, algorithm="HS256")

    r = await client.post("/api/whatsapp-addon/order", headers=_auth(receptionist))
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_buying_twice_is_refused(client, db):
    org, br = await _clinic(db)
    br.whatsapp_addon = True
    await db.commit()
    r = await client.post(
        "/api/whatsapp-addon/order", headers=_auth(_owner(str(org.id), str(br.id)))
    )
    assert r.status_code == 409
    assert "already active" in r.text


@pytest.mark.asyncio
async def test_bank_mandate_addon_is_blocked_before_money_is_taken(
    client, db, monkeypatch
):
    from backend.routers import payments

    org, branch = await _clinic(db)
    org.razorpay_subscription_id = "sub_bank_mandate"
    org.razorpay_subscription_status = "active"
    await db.commit()

    class Subscription:
        @staticmethod
        def fetch(_subscription_id):
            return {"payment_method": "emandate"}

    class Order:
        @staticmethod
        def create(_payload):
            raise AssertionError("no order may be created for an immutable mandate")

    provider = type(
        "Provider",
        (),
        {"subscription": Subscription(), "order": Order()},
    )()
    monkeypatch.setattr(payments, "_get_client", lambda: provider)

    response = await client.post(
        "/api/whatsapp-addon/order",
        headers=_auth(_owner(str(org.id), str(branch.id))),
    )

    assert response.status_code == 409
    assert "bank mandate cannot be changed" in response.text


@pytest.mark.asyncio
async def test_verify_enables_only_the_branch_named_by_the_server_set_order(db):
    """RULE 1: the branch comes from the ORDER's notes, never the client. A
    forged verify must not switch a paid feature on for another clinic."""
    from backend.routers.payments import _enable_whatsapp_addon

    _org_a, br_a = await _clinic(db)
    org_b, br_b = await _clinic(db)

    # Notes naming branch B under org B — the only branch that may change.
    await _enable_whatsapp_addon(
        db, {"branch_id": str(br_b.id), "org_id": str(org_b.id)}, "pay_1"
    )
    await db.refresh(br_a)
    await db.refresh(br_b)
    assert br_b.whatsapp_addon is True
    assert br_a.whatsapp_addon is False, "another clinic's branch must be untouched"


@pytest.mark.asyncio
async def test_a_branch_id_from_a_different_org_is_ignored(db):
    """Mismatched org/branch pairing is the shape a forged note would take."""
    _org_a, br_a = await _clinic(db)
    org_b, _br_b = await _clinic(db)
    from backend.routers.payments import _enable_whatsapp_addon

    await _enable_whatsapp_addon(
        db, {"branch_id": str(br_a.id), "org_id": str(org_b.id)}, "pay_2"
    )
    await db.refresh(br_a)
    assert br_a.whatsapp_addon is False


@pytest.mark.asyncio
async def test_enabling_twice_is_a_no_op(db):
    """Razorpay redelivers; a second verify must not compound anything."""
    from backend.routers.payments import _enable_whatsapp_addon

    org, br = await _clinic(db)
    for payment in ("pay_a", "pay_a"):
        await _enable_whatsapp_addon(
            db, {"branch_id": str(br.id), "org_id": str(org.id)}, payment
        )
    await db.refresh(br)
    assert br.whatsapp_addon is True


@pytest.mark.asyncio
async def test_signed_webhook_enables_addon_when_browser_never_verifies(
    client, db, monkeypatch
):
    org, branch = await _clinic(db)
    secret = "addon-webhook-secret"
    monkeypatch.setattr(settings, "razorpay_webhook_secret", secret)
    body = {
        "event": "order.paid",
        "payload": {
            "order": {"entity": {"notes": {
                "kind": "whatsapp_addon",
                "org_id": str(org.id),
                "branch_id": str(branch.id),
            }}},
            "payment": {"entity": {"id": "pay_addon_webhook_1"}},
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
    assert response.json()["status"] == "addon_enabled"
    await db.refresh(branch)
    assert branch.whatsapp_addon is True


@pytest.mark.asyncio
async def test_the_plan_card_reports_which_whatsapp_state_applies(client, db):
    org, br = await _clinic(db)
    tok = _auth(_owner(str(org.id), str(br.id)))

    body = (await client.get("/api/plan", headers=tok)).json()
    assert body["whatsapp_included"] is False
    assert body["whatsapp_addon"] is False

    br.whatsapp_addon = True
    await db.commit()
    body = (await client.get("/api/plan", headers=tok)).json()
    assert body["whatsapp_addon"] is True


@pytest.mark.asyncio
async def test_a_pending_growth_upgrade_still_requires_the_addon(client, db):
    from datetime import date, timedelta

    org, br = await _clinic(db)
    org.pending_plan = "clinic"
    org.pending_plan_effective = date.today() + timedelta(days=8)
    await db.commit()

    body = (await client.get(
        "/api/plan", headers=_auth(_owner(str(org.id), str(br.id)))
    )).json()
    assert body["whatsapp_included_pending"] is False
