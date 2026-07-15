"""Forgot/reset password via email OTP (new 2026-06-23).

A clinic that forgot its password requests a code, enters it with a new
password, and is signed straight in. Covers the happy path, no
account-existence oracle, weak-password rejection, and wrong-code rejection.
Uses the dev-echo OTP path (code returned in the response) like the signup
tests.
"""
import uuid

import httpx
import pytest
import pytest_asyncio

GOOD_PW = "Clinic@2024"
NEW_PW = "Clinic@2025New"


@pytest.fixture(autouse=True)
def _no_otp_provider(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "resend_api_key", "", raising=False)
    monkeypatch.setattr(settings, "smtp_host", "", raising=False)
    monkeypatch.setattr(settings, "msg91_auth_key", "", raising=False)
    monkeypatch.setattr(settings, "otp_dev_echo", True, raising=False)
    monkeypatch.setattr(settings, "app_env", "development", raising=False)
    # The happy-path test makes >5 auth calls in one go; without a bypass the
    # shared 5/min auth limiter would 429 before the assertions. testclient is
    # the ASGITransport peer IP.
    monkeypatch.setenv("RATE_LIMIT_BYPASS_IPS", "testclient")


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _unique_email():
    return f"clinic-{uuid.uuid4().hex[:8]}@realclinic.in"


async def _register(client, email):
    codes = (await client.post("/auth/request-otp", json={"email": email})).json()
    reg = await client.post(
        "/auth/register",
        json={
            "clinic_name": "Reset Clinic",
            "owner_name": "Owner",
            "email": email,
            "password": GOOD_PW,
            "email_otp": codes["dev_email_code"],
        },
    )
    assert reg.status_code == 201, reg.text


@pytest.mark.asyncio
async def test_full_reset_flow_then_login_with_new_password(client, db):
    email = _unique_email()
    await _register(client, email)

    # Request a reset code
    fp = await client.post("/auth/forgot-password", json={"email": email})
    assert fp.status_code == 200
    code = fp.json()["dev_email_code"]
    assert code  # account exists → code issued

    # Reset with the code + new password → signed in (token returned)
    rp = await client.post(
        "/auth/reset-password",
        json={"email": email, "code": code, "new_password": NEW_PW},
    )
    assert rp.status_code == 200, rp.text
    assert rp.json()["access_token"]

    # New password works, old one does not
    assert (await client.post("/auth/login", json={"email": email, "password": NEW_PW})).status_code == 200
    assert (await client.post("/auth/login", json={"email": email, "password": GOOD_PW})).status_code == 401


@pytest.mark.asyncio
async def test_forgot_password_unknown_email_no_oracle(client, db):
    # Unknown account → same 200 shape, but NO code is issued (no enumeration).
    r = await client.post("/auth/forgot-password", json={"email": _unique_email()})
    assert r.status_code == 200
    assert r.json()["dev_email_code"] is None


@pytest.mark.asyncio
async def test_reset_rejects_weak_password(client, db):
    email = _unique_email()
    await _register(client, email)
    code = (await client.post("/auth/forgot-password", json={"email": email})).json()["dev_email_code"]
    r = await client.post(
        "/auth/reset-password",
        json={"email": email, "code": code, "new_password": "weak"},
    )
    assert r.status_code == 422


@pytest.mark.asyncio
async def test_reset_rejects_wrong_code(client, db):
    email = _unique_email()
    await _register(client, email)
    await client.post("/auth/forgot-password", json={"email": email})
    r = await client.post(
        "/auth/reset-password",
        json={"email": email, "code": "000000", "new_password": NEW_PW},
    )
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_wrong_reset_code_does_not_feed_ip_blocklist(client, db, monkeypatch):
    """Vinay 2026-07-15 ("both codes, none worked"): a wrong reset code must NOT
    increment the 1-hour IP blocklist. Otherwise 5 fumbled codes ban the device
    and then reject even the CORRECT code at check_ip_blocklist before it is
    checked. Brute force is already bounded by the per-code attempt cap."""
    import backend.routers.auth as auth_mod

    email = _unique_email()
    await _register(client, email)
    await client.post("/auth/forgot-password", json={"email": email})

    calls = {"n": 0}

    async def _spy(ip):
        calls["n"] += 1

    monkeypatch.setattr(auth_mod, "record_failed_login", _spy)
    r = await client.post(
        "/auth/reset-password",
        json={"email": email, "code": "000000", "new_password": NEW_PW},
    )
    assert r.status_code == 401
    assert calls["n"] == 0  # reset failures must never feed the IP block


@pytest.mark.asyncio
async def test_only_latest_reset_code_valid(client, db):
    """SECURITY (#379): only the newest code is valid. Two codes issued (user
    requested twice / tapped resend) — the OLDER code is rejected (401), the
    NEWEST resets the password (200). A pool of valid codes would widen brute
    force."""
    email = _unique_email()
    await _register(client, email)
    c1 = (await client.post("/auth/forgot-password", json={"email": email})).json()["dev_email_code"]
    c2 = (await client.post("/auth/forgot-password", json={"email": email})).json()["dev_email_code"]
    assert c1 and c2 and c1 != c2

    older = await client.post(
        "/auth/reset-password",
        json={"email": email, "code": c1, "new_password": NEW_PW},
    )
    assert older.status_code == 401  # superseded code is dead

    latest = await client.post(
        "/auth/reset-password",
        json={"email": email, "code": c2, "new_password": NEW_PW},
    )
    assert latest.status_code == 200, latest.text
