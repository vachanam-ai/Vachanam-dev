"""WA MVP1 Task 9 — router layer for the Embedded Signup connect flow:
POST/GET/DELETE /branches/{id}/whatsapp/connect.

Needs Docker (Postgres + Redis) — uses the `db`/`redis` fixtures from
tests/conftest.py. Every Graph call is mocked via `wa_connect.connect_branch`
(no network) — this file proves auth, RULE 1 uniqueness, and DB persistence,
not the Meta integration itself (see test_wa_connect.py for that).
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from sqlalchemy import select

from backend.config import settings
from backend.models.schema import Branch, Organization
from backend.services import wa_connect
from backend.services.crypto import decrypt_secret, encrypt_secret


@pytest.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _jwt(*, role, org_id=None, branch_ids=None, is_admin=False):
    import jwt

    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": f"{role}@wac.test", "role": role,
            "org_id": org_id, "branch_ids": branch_ids or [], "is_admin": is_admin,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm="HS256",
    )


def _auth(t):
    return {"Authorization": f"Bearer {t}"}


async def _clinic(db, **branch_kwargs):
    org = Organization(
        name="WaConnOrg", owner_phone="+919000700077",
        owner_email=f"wac-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="WaConnBranch",
        whatsapp_number=f"+9177{str(uuid.uuid4().int)[:9]}", status="active",
        **branch_kwargs,
    )
    db.add(branch)
    await db.commit()
    return org, branch


@pytest.fixture
def fake_connect(monkeypatch):
    """No network: mutates the branch exactly as the real wa_connect.connect_branch
    contract does, so the router's persistence/response logic is exercised for
    real."""
    calls = []

    async def _fake(branch, *, code, waba_id, phone_number_id):
        calls.append(
            {"code": code, "waba_id": waba_id, "phone_number_id": phone_number_id}
        )
        branch.wa_waba_id = waba_id
        branch.wa_phone_number_id = phone_number_id
        branch.wa_token_enc = encrypt_secret("FAKE_BUSINESS_TOKEN")
        branch.wa_verified_name = "Test Clinic"
        branch.wa_status = "connected"
        branch.wa_connected_at = datetime.now(timezone.utc)
        return {"registered": True, "verified_name": "Test Clinic"}

    monkeypatch.setattr(wa_connect, "connect_branch", _fake)
    return calls


_BODY = {
    "code": "AUTHORIZATION_CODE_ABCDEFG",
    "waba_id": "123456789",
    "phone_number_id": "987654321",
}


# ── happy path + persistence ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_org_admin_connects_own_branch(db, client, fake_connect):
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner), json=_BODY,
    )

    assert r.status_code == 201, r.text
    body = r.json()
    assert body["wa_status"] == "connected"
    assert body["wa_waba_id"] == "123456789"
    assert body["wa_verified_name"] == "Test Clinic"
    assert "wa_token_enc" not in body
    assert fake_connect == [
        {"code": "AUTHORIZATION_CODE_ABCDEFG", "waba_id": "123456789",
         "phone_number_id": "987654321"}
    ]

    # The request was served by the app's OWN db session — refresh this
    # fixture's session's identity-mapped copy to see its committed writes
    # (mirrors the `await db.refresh(tok)` pattern in test_wa_plan_no_voice.py).
    await db.refresh(branch)
    assert branch.wa_status == "connected"
    assert branch.wa_waba_id == "123456789"
    assert decrypt_secret(branch.wa_token_enc) == "FAKE_BUSINESS_TOKEN"


# ── manual connect (Embedded Signup unavailable) ─────────────────────────────


@pytest.fixture
def fake_manual_connect(monkeypatch):
    """Same contract as fake_connect, for connect_branch_manual: takes a token
    instead of a code and stores THAT token, so a test can prove the owner's
    own credential is what ends up on the branch."""
    calls = []

    async def _fake(branch, *, token, waba_id, phone_number_id):
        calls.append(
            {"token": token, "waba_id": waba_id, "phone_number_id": phone_number_id}
        )
        branch.wa_waba_id = waba_id
        branch.wa_phone_number_id = phone_number_id
        branch.wa_token_enc = encrypt_secret(token)
        branch.wa_verified_name = "Manual Clinic"
        branch.wa_status = "connected"
        branch.wa_connected_at = datetime.now(timezone.utc)
        return {"registered": False, "verified_name": "Manual Clinic"}

    monkeypatch.setattr(wa_connect, "connect_branch_manual", _fake)
    return calls


_MANUAL_BODY = {
    "waba_id": "555000111",
    "phone_number_id": "555000222",
    "access_token": "EAAG" + "x" * 40,
}


@pytest.mark.asyncio
async def test_owner_connects_by_pasting_the_ids(db, client, fake_manual_connect):
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect/manual",
        headers=_auth(owner), json=_MANUAL_BODY,
    )

    assert r.status_code == 201, r.text
    assert r.json()["wa_status"] == "connected"
    assert r.json()["wa_waba_id"] == "555000111"
    assert "access_token" not in r.json() and "wa_token_enc" not in r.json()

    await db.refresh(branch)
    # The OWNER's token is stored — never the platform token (RULE 1: bridge
    # mode is super_admin-only and must not be reachable from the clinic page).
    assert decrypt_secret(branch.wa_token_enc) == _MANUAL_BODY["access_token"]
    assert branch.wa_waba_id == "555000111"


@pytest.mark.asyncio
async def test_manual_connect_requires_a_token(db, client, fake_manual_connect):
    """Without a token the branch would fall back to settings.meta_access_token
    — letting any clinic type Vachanam's WABA id and send from the platform
    account. The field is required, so this can never reach the service."""
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))

    for bad in ({k: v for k, v in _MANUAL_BODY.items() if k != "access_token"},
                {**_MANUAL_BODY, "access_token": ""},
                {**_MANUAL_BODY, "access_token": "short"}):
        r = await client.post(
            f"/branches/{branch.id}/whatsapp/connect/manual",
            headers=_auth(owner), json=bad,
        )
        assert r.status_code == 422, r.text
    assert fake_manual_connect == []


@pytest.mark.asyncio
async def test_manual_connect_strips_pasted_whitespace(db, client, fake_manual_connect):
    """A token copied from Meta's dashboard drags a trailing newline along and
    then fails Graph auth with an error no clinic owner can diagnose."""
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))

    await client.post(
        f"/branches/{branch.id}/whatsapp/connect/manual", headers=_auth(owner),
        json={**_MANUAL_BODY, "access_token": f"  {_MANUAL_BODY['access_token']}\n",
              "waba_id": " 555000111 "},
    )
    assert fake_manual_connect[0]["token"] == _MANUAL_BODY["access_token"]
    assert fake_manual_connect[0]["waba_id"] == "555000111"


@pytest.mark.asyncio
async def test_manual_connect_is_owner_only(db, client, fake_manual_connect):
    org, branch = await _clinic(db)

    receptionist = _jwt(role="receptionist", org_id=str(org.id),
                        branch_ids=[str(branch.id)])
    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect/manual",
        headers=_auth(receptionist), json=_MANUAL_BODY,
    )
    assert r.status_code == 403

    admin = _jwt(role="super_admin", is_admin=True)
    r2 = await client.post(
        f"/branches/{branch.id}/whatsapp/connect/manual",
        headers=_auth(admin), json=_MANUAL_BODY,
    )
    assert r2.status_code == 403
    assert fake_manual_connect == []


@pytest.mark.asyncio
async def test_manual_connect_cannot_claim_another_clinics_waba(
    db, client, fake_manual_connect,
):
    """RULE 1: pasting IDs is unauthenticated input — the uniqueness guard is
    what stops a clinic typing a WABA it does not own."""
    org1, b1 = await _clinic(db, wa_waba_id="555000111")
    org2, b2 = await _clinic(db)
    owner2 = _jwt(role="org_admin", org_id=str(org2.id))

    r = await client.post(
        f"/branches/{b2.id}/whatsapp/connect/manual",
        headers=_auth(owner2), json=_MANUAL_BODY,
    )
    assert r.status_code == 409
    # Checked BEFORE any Graph call — no wasted round-trip, no partial state.
    assert fake_manual_connect == []
    await db.refresh(b2)
    assert b2.wa_waba_id is None


@pytest.mark.asyncio
async def test_manual_connect_rejects_non_numeric_ids(db, client, fake_manual_connect):
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))
    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect/manual", headers=_auth(owner),
        json={**_MANUAL_BODY, "phone_number_id": "not-an-id"},
    )
    assert r.status_code == 422
    assert fake_manual_connect == []


@pytest.mark.asyncio
async def test_manual_connect_subscribe_failure_is_surfaced(db, client, monkeypatch):
    """The subscribe is mandatory on this path too — a branch that looks
    connected but never receives a webhook is worse than an honest failure."""
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))

    async def _boom(branch, *, token, waba_id, phone_number_id):
        raise wa_connect.WaConnectError(502, "could not subscribe")

    monkeypatch.setattr(wa_connect, "connect_branch_manual", _boom)
    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect/manual",
        headers=_auth(owner), json=_MANUAL_BODY,
    )
    assert r.status_code == 502
    await db.refresh(branch)
    assert branch.wa_waba_id is None


@pytest.mark.asyncio
async def test_get_status_never_returns_the_token(db, client, fake_connect):
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))
    await client.post(
        f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner), json=_BODY,
    )

    r = await client.get(f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is True
    assert body["wa_status"] == "connected"
    assert body["wa_waba_id"] == "123456789"
    assert "wa_token_enc" not in body
    assert "code" not in body


@pytest.mark.asyncio
async def test_get_status_before_connect_is_none(db, client):
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))

    r = await client.get(f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["connected"] is False
    assert body["wa_status"] == "none"


# ── auth: org_admin only, RULE 1 tenant isolation ───────────────────────────


@pytest.mark.asyncio
async def test_receptionist_cannot_connect(db, client, fake_connect):
    org, branch = await _clinic(db)
    recept = _jwt(role="receptionist", org_id=str(org.id), branch_ids=[str(branch.id)])

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect", headers=_auth(recept), json=_BODY,
    )
    assert r.status_code == 403
    assert fake_connect == []


@pytest.mark.asyncio
async def test_super_admin_locked_out_of_connect(db, client, fake_connect):
    """RULE 1 — platform admin cannot touch clinic data, even to link WhatsApp.
    Vinay uses the concierge /admin endpoint, not this one."""
    org, branch = await _clinic(db)
    admin = _jwt(role="super_admin", is_admin=True)

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect", headers=_auth(admin), json=_BODY,
    )
    assert r.status_code == 403
    assert fake_connect == []


@pytest.mark.asyncio
async def test_org_admin_cannot_connect_another_orgs_branch(db, client, fake_connect):
    org_a, branch_a = await _clinic(db)
    org_b, branch_b = await _clinic(db)
    owner_b = _jwt(role="org_admin", org_id=str(org_b.id))

    r = await client.post(
        f"/branches/{branch_a.id}/whatsapp/connect", headers=_auth(owner_b), json=_BODY,
    )
    assert r.status_code == 403
    assert fake_connect == []


@pytest.mark.asyncio
async def test_receptionist_cannot_disconnect(db, client):
    org, branch = await _clinic(db, wa_waba_id="X1", wa_status="connected")
    recept = _jwt(role="receptionist", org_id=str(org.id), branch_ids=[str(branch.id)])

    r = await client.delete(
        f"/branches/{branch.id}/whatsapp/connect", headers=_auth(recept),
    )
    assert r.status_code == 403


# ── RULE 1: wa_waba_id uniqueness — clean 409, never a silent overwrite ─────


@pytest.mark.asyncio
async def test_waba_already_linked_to_another_branch_is_409(db, client, fake_connect):
    org_a, branch_a = await _clinic(db, wa_waba_id="123456789", wa_status="connected")
    org_b, branch_b = await _clinic(db)
    owner_b = _jwt(role="org_admin", org_id=str(org_b.id))

    r = await client.post(
        f"/branches/{branch_b.id}/whatsapp/connect", headers=_auth(owner_b), json=_BODY,
    )
    assert r.status_code == 409
    # Checked BEFORE any Graph call — no wasted round-trip, no partial state.
    assert fake_connect == []

    row = (
        await db.execute(select(Branch).where(Branch.id == branch_b.id))
    ).scalar_one()
    assert row.wa_waba_id is None
    assert row.wa_status == "none"


# ── failure mapping ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_connect_error_maps_to_the_raised_status(db, client, monkeypatch):
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))

    async def _boom(branch, *, code, waba_id, phone_number_id):
        raise wa_connect.WaConnectError(502, "Could not connect to WhatsApp — please try again.")

    monkeypatch.setattr(wa_connect, "connect_branch", _boom)

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner), json=_BODY,
    )
    assert r.status_code == 502
    assert "please try again" in r.json()["detail"]

    row = (
        await db.execute(select(Branch).where(Branch.id == branch.id))
    ).scalar_one()
    assert row.wa_status == "none"  # nothing committed on failure


@pytest.mark.asyncio
async def test_non_numeric_waba_id_is_422(db, client, fake_connect):
    org, branch = await _clinic(db)
    owner = _jwt(role="org_admin", org_id=str(org.id))

    r = await client.post(
        f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner),
        json={**_BODY, "waba_id": "not-a-number"},
    )
    assert r.status_code == 422
    assert fake_connect == []


# ── disconnect ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_org_admin_disconnects_and_clears_credentials(db, client):
    org, branch = await _clinic(
        db, wa_waba_id="555", wa_phone_number_id="666",
        wa_token_enc=encrypt_secret("SOME_TOKEN"), wa_verified_name="Old Name",
        wa_status="connected",
    )
    owner = _jwt(role="org_admin", org_id=str(org.id))

    r = await client.delete(
        f"/branches/{branch.id}/whatsapp/connect", headers=_auth(owner),
    )
    assert r.status_code == 200, r.text
    assert r.json()["wa_status"] == "disconnected"

    await db.refresh(branch)
    assert branch.wa_waba_id is None
    assert branch.wa_token_enc is None
    assert branch.wa_verified_name is None
    assert branch.wa_phone_number_id is None
    assert branch.wa_status == "disconnected"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
