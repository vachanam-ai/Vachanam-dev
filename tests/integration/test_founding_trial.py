"""#426 founding free trial (Vinay 2026-07-20): the first
FOUNDING_TRIAL_SLOTS self-serve signups get the 14-day / 300-min trial back;
after that (or with the offer flipped off) signups start paused as per #392.

Deterministic regardless of test-DB residue: each test monkeypatches
billing_math.FOUNDING_TRIAL_SLOTS instead of trusting the live count.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.models.schema import Organization
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
            "accepted_terms": True,
            "email_otp": codes["dev_email_code"],
        },
    )


@pytest.mark.asyncio
async def test_slot_available_grants_14_day_trial(client, db, monkeypatch):
    monkeypatch.setattr(billing_math, "TRIAL_FOR_ALL", False)
    monkeypatch.setattr(billing_math, "FOUNDING_TRIAL_SLOTS", 10**9)
    email = _unique_email()
    r = await _register(client, email)
    assert r.status_code == 201, r.text
    org = (
        await db.execute(select(Organization).where(Organization.owner_email == email))
    ).scalar_one()
    assert org.status == "trial"
    assert org.trial_ends_at is not None
    # 14-day window (PILOT_DAYS), sanity-band not exact-clock.
    from datetime import datetime, timedelta, timezone

    delta = org.trial_ends_at - datetime.now(timezone.utc)
    assert timedelta(days=13) < delta <= timedelta(days=14)


@pytest.mark.asyncio
async def test_offer_off_starts_paused(client, db, monkeypatch):
    monkeypatch.setattr(billing_math, "TRIAL_FOR_ALL", False)
    monkeypatch.setattr(billing_math, "FOUNDING_TRIAL_SLOTS", 0)
    email = _unique_email()
    r = await _register(client, email)
    assert r.status_code == 201, r.text
    org = (
        await db.execute(select(Organization).where(Organization.owner_email == email))
    ).scalar_one()
    assert org.status == "paused"
    assert org.trial_ends_at is None


@pytest.mark.asyncio
async def test_slots_exhausted_starts_paused(client, db, monkeypatch):
    # Cap = 1, burn the slot, next signup must be paused.
    monkeypatch.setattr(billing_math, "TRIAL_FOR_ALL", False)
    monkeypatch.setattr(billing_math, "FOUNDING_TRIAL_SLOTS", 1)
    first, second = _unique_email(), _unique_email()
    assert (await _register(client, first)).status_code == 201
    assert (await _register(client, second)).status_code == 201
    org1 = (
        await db.execute(select(Organization).where(Organization.owner_email == first))
    ).scalar_one()
    org2 = (
        await db.execute(select(Organization).where(Organization.owner_email == second))
    ).scalar_one()
    # Residue orgs in the shared test DB may already hold the single slot —
    # then BOTH are paused; otherwise first=trial, second=paused. Never both trial.
    assert org2.status == "paused" and org2.trial_ends_at is None
    assert org1.status in ("trial", "paused")


@pytest.mark.asyncio
async def test_public_slots_endpoint(client, db, monkeypatch):  # db: creates schema
    # Capped mode (TRIAL_FOR_ALL off): counter is exposed.
    monkeypatch.setattr(billing_math, "TRIAL_FOR_ALL", False)
    monkeypatch.setattr(billing_math, "FOUNDING_TRIAL_SLOTS", 10)
    body = (await client.get("/auth/founding-slots")).json()
    assert body["trial_for_all"] is False
    assert body["slots_total"] == 10
    assert 0 <= body["slots_left"] <= 10

    monkeypatch.setattr(billing_math, "FOUNDING_TRIAL_SLOTS", 0)
    body = (await client.get("/auth/founding-slots")).json()
    assert body == {"trial_for_all": False, "slots_total": 0, "slots_left": 0}


@pytest.mark.asyncio
async def test_trial_for_all_grants_every_signup(client, db, monkeypatch):
    """#433 (Vinay: "make 14days free trail common across"): with TRIAL_FOR_ALL,
    every new clinic gets the 14-day trial regardless of the slot count, and
    the public endpoint advertises it with no scarcity counter."""
    monkeypatch.setattr(billing_math, "TRIAL_FOR_ALL", True)
    monkeypatch.setattr(billing_math, "FOUNDING_TRIAL_SLOTS", 0)  # irrelevant now
    body = (await client.get("/auth/founding-slots")).json()
    assert body == {"trial_for_all": True, "slots_total": -1, "slots_left": -1}

    email = _unique_email()
    assert (await _register(client, email)).status_code == 201
    org = (
        await db.execute(select(Organization).where(Organization.owner_email == email))
    ).scalar_one()
    assert org.status == "trial"
    assert org.trial_ends_at is not None
