"""Founding 100: unlimited 14-day trial, then normal paid pricing."""
import uuid
from datetime import datetime, timezone

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.models.schema import BillingCycle, Branch, CallLog, Organization
from backend.routers.payments import activate_subscription
from backend.services import billing_math

GOOD_PW = "Clinic@2024"


@pytest.fixture(autouse=True)
def _no_otp_provider(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(settings, "msg91_auth_key", "", raising=False)
    monkeypatch.setattr(settings, "otp_dev_echo", True, raising=False)
    monkeypatch.setattr(settings, "app_env", "development", raising=False)
    monkeypatch.setenv("RATE_LIMIT_BYPASS_IPS", "testclient")


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _unique_email():
    return f"founding-{uuid.uuid4().hex[:8]}@realclinic.in"


async def _register(client, email):
    codes = (await client.post("/auth/request-otp", json={"email": email})).json()
    return await client.post(
        "/auth/register",
        json={
            "clinic_name": "Founding Test Clinic",
            "owner_name": "Owner",
            "email": email,
            "password": GOOD_PW,
            "plan": "solo",
            "accepted_terms": True,
            "email_otp": codes["dev_email_code"],
        },
    )


@pytest.mark.asyncio
async def test_available_slot_starts_unlimited_fourteen_day_trial(client, db, monkeypatch):
    monkeypatch.setattr(billing_math, "FOUNDING_CLINIC_SLOTS", 10**9)
    email = _unique_email()
    response = await _register(client, email)
    assert response.status_code == 201, response.text

    org = (
        await db.execute(select(Organization).where(Organization.owner_email == email))
    ).scalar_one()
    assert org.status == "trial"
    assert org.trial_ends_at is not None
    assert org.founding_member is True
    assert org.founding_credit_minutes == 0

    branch = (
        await db.execute(select(Branch).where(Branch.org_id == org.id))
    ).scalar_one()
    db.add(CallLog(
        branch_id=branch.id,
        call_type="inbound",
        caller_last4="0000",
        answered=True,
        started_at=datetime.now(timezone.utc),
        duration_seconds=100_000 * 60,
    ))
    await db.commit()
    summary = await client.get(
        "/api/billing/summary",
        headers={"Authorization": f"Bearer {response.json()['access_token']}"},
    )
    assert summary.status_code == 200, summary.text
    bill = summary.json()
    assert bill["trial_unlimited"] is True
    assert bill["minutes_used"] == 100_000
    assert bill["overage_minutes"] == 0
    assert bill["overage_amount"] == 0


@pytest.mark.asyncio
async def test_offer_off_creates_normal_paused_clinic(client, db, monkeypatch):
    monkeypatch.setattr(billing_math, "FOUNDING_CLINIC_SLOTS", 0)
    email = _unique_email()
    response = await _register(client, email)
    assert response.status_code == 201, response.text

    org = (
        await db.execute(select(Organization).where(Organization.owner_email == email))
    ).scalar_one()
    assert org.status == "paused"
    assert org.founding_member is False
    assert org.founding_credit_minutes == 0


@pytest.mark.asyncio
async def test_public_counter_reports_unlimited_trial_and_capacity(client, db, monkeypatch):
    monkeypatch.setattr(billing_math, "FOUNDING_CLINIC_SLOTS", 100)
    body = (await client.get("/auth/founding-slots")).json()
    assert body["trial_for_all"] is False
    assert body["slots_total"] == 100
    assert 0 <= body["slots_left"] <= 100
    assert body["credit_minutes"] == 0
    assert body["trial_days"] == 14
    assert body["trial_unlimited"] is True


@pytest.mark.asyncio
async def test_credit_lives_only_on_first_paid_cycle(db):
    org = Organization(
        name=f"Founding lifecycle {uuid.uuid4().hex[:6]}",
        owner_phone="",
        owner_email=f"lifecycle-{uuid.uuid4().hex[:8]}@realclinic.in",
        plan="solo",
        status="paused",
        founding_member=True,
        founding_credit_minutes=500,
    )
    db.add(org)
    await db.commit()
    await db.refresh(org)

    first = await activate_subscription(
        db, str(org.id), "solo", f"pay_{uuid.uuid4().hex[:12]}"
    )
    assert first == "activated"
    first_cycle = (
        await db.execute(
            select(BillingCycle)
            .where(BillingCycle.org_id == org.id)
            .order_by(BillingCycle.cycle_start)
        )
    ).scalars().first()
    assert first_cycle.included_minutes == 500
    assert org.founding_credit_minutes == 500

    second = await activate_subscription(
        db, str(org.id), "solo", f"pay_{uuid.uuid4().hex[:12]}"
    )
    assert second == "activated"
    cycles = (
        await db.execute(
            select(BillingCycle)
            .where(BillingCycle.org_id == org.id)
            .order_by(BillingCycle.cycle_start, BillingCycle.created_at)
        )
    ).scalars().all()
    assert [cycle.included_minutes for cycle in cycles] == [500, 0]
    assert org.founding_member is True
    assert org.founding_credit_minutes == 0
