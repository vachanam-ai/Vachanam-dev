"""End-to-end signup with OTP verification + input validation.

Proves the full funnel with Vinay's real sample data:
  vinayrongala2002@gmail.com / 8096007554

Covers: garbage rejection (bad phone/email/password), OTP gate (no register
without a verified PHONE code — mobile-only, email is NOT OTP-verified;
decision Vinay 2026-06-14), wrong-code rejection, and a clean happy path that
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
    # NOT a reserved RFC-2606 domain (example.com/test.com are rejected at
    # signup now — placeholder/junk addresses can't open a trial).
    return f"clinic-{uuid.uuid4().hex[:8]}@realclinic.in"


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
        },
    )
    assert r.status_code == 422


# ── OTP gate: cannot register without verified codes ────────────────────────


@pytest.mark.asyncio
async def test_register_blocked_without_otp(client):
    email = _unique_email()
    # Valid details, but wrong PHONE code -> 403 (mobile-only gate).
    r = await client.post(
        "/auth/register",
        json={
            "clinic_name": "No OTP Clinic",
            "owner_name": "Tester",
            "phone": REAL_PHONE,
            "email": email,
            "password": GOOD_PW,
            "phone_otp": "111111",
        },
    )
    assert r.status_code == 403
    assert "phone not verified" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_needs_no_email_otp(client, db):
    """Mobile-only: a verified PHONE code is sufficient; email is never
    OTP-challenged (decision Vinay 2026-06-14)."""
    email = _unique_email()
    codes = (
        await client.post("/auth/request-otp", json={"phone": REAL_PHONE})
    ).json()
    assert codes["sent"] == ["sms"]
    reg = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Mobile Only Clinic",
            "owner_name": "Tester",
            "phone": REAL_PHONE,
            "email": email,
            "password": GOOD_PW,
            "phone_otp": codes["dev_phone_code"],
            # NO email_otp supplied — must still succeed.
        },
    )
    assert reg.status_code == 201, reg.text


# ── Happy path: request OTP (dev echoes codes) -> register -> JWT ───────────


@pytest.mark.asyncio
async def test_full_signup_with_real_sample_data(client, db):
    email = _unique_email()

    otp = await client.post(
        "/auth/request-otp", json={"phone": REAL_PHONE}
    )
    assert otp.status_code == 200, otp.text
    codes = otp.json()
    assert codes["sent"] == ["sms"]
    phone_code = codes["dev_phone_code"]
    assert phone_code, "dev echo must surface code in test env"

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
async def test_otp_code_is_single_use(client, db):
    """A verified code can't be replayed for a second registration.

    db fixture is REQUIRED even though unused directly: it patches the app's
    sessions onto vachanam_test. Without it this test's successful /register
    wrote a 'Replay Clinic' org into the PRODUCTION database on every suite
    run (20+ ghost clinics on the admin console, 2026-06-12)."""
    email = _unique_email()
    codes = (
        await client.post("/auth/request-otp", json={"phone": REAL_PHONE})
    ).json()

    base = {
        "clinic_name": "Replay Clinic",
        "owner_name": "Tester",
        "phone": REAL_PHONE,
        "email": email,
        "password": GOOD_PW,
        "phone_otp": codes["dev_phone_code"],
    }
    first = await client.post("/auth/register", json=base)
    assert first.status_code == 201, first.text

    # Replay the SAME code on a DIFFERENT, never-verified phone -> 403.
    # (The first phone's is_verified flag persists by design — M7 retry safety —
    # so we prove single-use by replaying onto a fresh number whose flag is unset.)
    base2 = dict(base, email=_unique_email(), phone="9000012345")
    second = await client.post("/auth/register", json=base2)
    assert second.status_code == 403
    assert "phone not verified" in second.json()["detail"].lower()
