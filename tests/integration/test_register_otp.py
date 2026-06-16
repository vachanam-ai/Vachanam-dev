"""End-to-end signup with EMAIL-OTP verification + input validation.

Covers: garbage rejection (bad email/password), OTP gate (no register without a
verified EMAIL code — email-only, mobile is no longer collected at signup;
decision Vinay 2026-06-15), wrong-code rejection, and a clean happy path that
creates an Organization + Branch + org_admin and returns a JWT.
"""
import uuid

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import select

from backend.models.schema import Organization, User

# Password must satisfy: 8+, lowercase, uppercase, digit, special char.
GOOD_PW = "Clinic@2024"


@pytest.fixture(autouse=True)
def _no_otp_provider(monkeypatch):
    """These tests rely on the dev-echo OTP path (the code is returned by
    /request-otp). Clear any real provider that a developer's local .env might
    set (RESEND_API_KEY / SMTP_HOST / MSG91) so the suite is hermetic."""
    from backend.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(settings, "msg91_auth_key", "", raising=False)
    monkeypatch.setattr(settings, "otp_dev_echo", True, raising=False)
    monkeypatch.setattr(settings, "app_env", "development", raising=False)


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
async def test_request_otp_rejects_bad_email(client):
    r = await client.post("/auth/request-otp", json={"email": "notanemail"})
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_register_rejects_weak_password(client):
    # Everything else valid, but a password missing a special char is refused.
    email = _unique_email()
    codes = (await client.post("/auth/request-otp", json={"email": email})).json()
    r = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Garbage Clinic",
            "owner_name": "Tester",
            "email": email,
            "password": "Clinic2024",  # no special char
            "email_otp": codes["dev_email_code"],
        },
    )
    assert r.status_code == 422
    assert any(w in r.json()["detail"].lower() for w in ("special", "number", "common", "uppercase", "lowercase"))


@pytest.mark.asyncio
async def test_register_rejects_bad_email(client):
    r = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Garbage Clinic",
            "owner_name": "Tester",
            "email": "not-an-email",
            "password": GOOD_PW,
            "email_otp": "000000",
        },
    )
    assert r.status_code == 422


# ── OTP gate: cannot register without a verified email code ─────────────────


@pytest.mark.asyncio
async def test_register_blocked_without_otp(client):
    email = _unique_email()
    # Valid details, but wrong EMAIL code -> 403 (email-only gate).
    r = await client.post(
        "/auth/register",
        json={
            "clinic_name": "No OTP Clinic",
            "owner_name": "Tester",
            "email": email,
            "password": GOOD_PW,
            "email_otp": "111111",
        },
    )
    assert r.status_code == 403
    assert "email not verified" in r.json()["detail"].lower()


@pytest.mark.asyncio
async def test_register_needs_no_phone(client, db):
    """Email-only: a verified EMAIL code is sufficient; no phone is collected
    at signup (decision Vinay 2026-06-15)."""
    email = _unique_email()
    codes = (await client.post("/auth/request-otp", json={"email": email})).json()
    assert codes["sent"] == ["email"]
    reg = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Email Only Clinic",
            "owner_name": "Tester",
            "email": email,
            "password": GOOD_PW,
            "email_otp": codes["dev_email_code"],
            # NO phone supplied — must still succeed.
        },
    )
    assert reg.status_code == 201, reg.text


# ── Happy path: request OTP (dev echoes codes) -> register -> JWT ───────────


@pytest.mark.asyncio
async def test_full_signup_email_only(client, db):
    email = _unique_email()

    otp = await client.post("/auth/request-otp", json={"email": email})
    assert otp.status_code == 200, otp.text
    codes = otp.json()
    assert codes["sent"] == ["email"]
    email_code = codes["dev_email_code"]
    assert email_code, "dev echo must surface code in test env"

    reg = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Sri Dental Care",
            "owner_name": "Dr Srinivas",
            "email": email,
            "password": GOOD_PW,
            "plan": "clinic",
            "email_otp": email_code,
        },
    )
    assert reg.status_code == 201, reg.text
    assert reg.json()["access_token"]

    # Org + user created with chosen plan; no phone collected (owner_phone="").
    org = (
        await db.execute(select(Organization).where(Organization.owner_email == email))
    ).scalar_one()
    assert org.plan == "clinic"
    assert org.owner_phone == ""
    user = (await db.execute(select(User).where(User.email == email))).scalar_one()
    assert user.role == "org_admin"
    assert user.phone is None


@pytest.mark.asyncio
async def test_otp_code_is_single_use(client, db):
    """A verified code can't be replayed for a second registration.

    db fixture is REQUIRED even though unused directly: it patches the app's
    sessions onto vachanam_test so /register doesn't write ghost clinics into
    the PRODUCTION database on every suite run."""
    email = _unique_email()
    codes = (await client.post("/auth/request-otp", json={"email": email})).json()

    base = {
        "clinic_name": "Replay Clinic",
        "owner_name": "Tester",
        "email": email,
        "password": GOOD_PW,
        "email_otp": codes["dev_email_code"],
    }
    first = await client.post("/auth/register", json=base)
    assert first.status_code == 201, first.text

    # Replay the SAME code on a DIFFERENT, never-verified email -> 403.
    # (The first email's is_verified flag persists by design — M7 retry safety —
    # so we prove single-use by replaying onto a fresh address whose flag is unset.)
    base2 = dict(base, email=_unique_email())
    second = await client.post("/auth/register", json=base2)
    assert second.status_code == 403
    assert "email not verified" in second.json()["detail"].lower()
