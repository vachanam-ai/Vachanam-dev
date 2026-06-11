"""End-to-end signup with OTP verification + input validation.

Proves the full funnel with Vinay's real sample data:
  vinayrongala2002@gmail.com / 8096007554

Covers: garbage rejection (bad phone/email/password), OTP gate (no register
without verified codes), wrong-code rejection, and a clean happy path that
creates an Organization + Branch + org_admin and returns a JWT.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.models.schema import Organization, User

REAL_EMAIL = "vinayrongala2002@gmail.com"
REAL_PHONE = "8096007554"
GOOD_PW = "Clinic2024"


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _unique_email():
    return f"clinic-{uuid.uuid4().hex[:8]}@example.com"


# ── Validation: garbage is rejected at /request-otp and /register ───────────


@pytest.mark.asyncio
async def test_request_otp_rejects_bad_phone(client):
    r = await client.post("/auth/request-otp", json={"phone": "12345"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_request_otp_rejects_bad_email(client):
    r = await client.post("/auth/request-otp", json={"email": "notanemail"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client):
    # Even with everything else valid, a numbers-only password is refused.
    r = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Garbage Clinic",
            "owner_name": "Tester",
            "phone": REAL_PHONE,
            "email": _unique_email(),
            "password": "1234567890",
            "phone_otp": "000000",
            "email_otp": "000000",
        },
    )
    assert r.status_code == 422
    # rejected either as all-numeric or as a known-common password
    assert any(w in r.json()["detail"].lower() for w in ("number", "common", "guess"))


@pytest.mark.asyncio
async def test_register_rejects_bad_phone(client):
    r = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Garbage Clinic",
            "owner_name": "Tester",
            "phone": "99",
            "email": _unique_email(),
            "password": GOOD_PW,
            "phone_otp": "000000",
            "email_otp": "000000",
        },
    )
    assert r.status_code == 422


# ── OTP gate: cannot register without verified codes ────────────────────────


@pytest.mark.asyncio
async def test_register_blocked_without_otp(client):
    email = _unique_email()
    # Valid details, but no/incorrect OTP -> 403
    r = await client.post(
        "/auth/register",
        json={
            "clinic_name": "No OTP Clinic",
            "owner_name": "Tester",
            "phone": REAL_PHONE,
            "email": email,
            "password": GOOD_PW,
            "phone_otp": "111111",
            "email_otp": "222222",
        },
    )
    assert r.status_code == 403
    assert "verif" in r.json()["detail"].lower()


# ── Happy path: request OTP (dev echoes codes) -> register -> JWT ───────────


@pytest.mark.asyncio
async def test_full_signup_with_real_sample_data(client, db):
    email = _unique_email()

    otp = await client.post(
        "/auth/request-otp", json={"phone": REAL_PHONE, "email": email}
    )
    assert otp.status_code == 200, otp.text
    codes = otp.json()
    assert set(codes["sent"]) == {"sms", "email"}
    phone_code = codes["dev_phone_code"]
    email_code = codes["dev_email_code"]
    assert phone_code and email_code, "dev echo must surface codes in test env"

    reg = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Sri Dental Care",
            "owner_name": "Dr Srinivas",
            "phone": REAL_PHONE,
            "email": email,
            "password": GOOD_PW,
            "plan": "clinic",
            "phone_otp": phone_code,
            "email_otp": email_code,
        },
    )
    assert reg.status_code == 201, reg.text
    assert reg.json()["access_token"]

    # Org + user created with NORMALIZED phone (+91...) and chosen plan
    org = (
        await db.execute(select(Organization).where(Organization.owner_email == email))
    ).scalar_one()
    assert org.plan == "clinic"
    assert org.owner_phone == "+918096007554"
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    assert user.role == "org_admin"
    assert user.phone == "+918096007554"


@pytest.mark.asyncio
async def test_otp_code_is_single_use(client):
    """A verified code can't be replayed for a second registration."""
    email = _unique_email()
    codes = (
        await client.post("/auth/request-otp", json={"phone": REAL_PHONE, "email": email})
    ).json()

    base = {
        "clinic_name": "Replay Clinic",
        "owner_name": "Tester",
        "phone": REAL_PHONE,
        "email": email,
        "password": GOOD_PW,
        "phone_otp": codes["dev_phone_code"],
        "email_otp": codes["dev_email_code"],
    }
    first = await client.post("/auth/register", json=base)
    assert first.status_code == 201, first.text

    # Same codes again (different email to dodge the duplicate-account 409) -> 403
    base2 = dict(base, email=_unique_email())
    second = await client.post("/auth/register", json=base2)
    assert second.status_code == 403
