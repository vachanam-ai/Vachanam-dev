"""GET /branches/{id}/whatsapp/signup-config — what the browser needs to open
Meta's Embedded Signup popup.

Vinay 2026-08-04: "Once we get business verified we need to embed link very
simply." One button, no IDs typed anywhere. The browser cannot open the popup
without an app_id and a config_id, and hardcoding those in the PWA bundle
would make a wrong config id a rebuild-and-redeploy instead of an env change.

The security line this file defends: app_id / config_id / graph_version are
PUBLIC (they ship inside Meta's own JS snippet). `meta_app_secret` is NOT, and
must never appear in any response — it is the half that lets our server spend
the one-time authorization code.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from backend.config import settings
from backend.models.schema import Branch, Organization


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
            "sub": str(uuid.uuid4()), "email": f"{role}@wasc.test", "role": role,
            "org_id": org_id, "branch_ids": branch_ids or [], "is_admin": is_admin,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm="HS256",
    )


async def _clinic(db):
    org = Organization(
        name="SignupCfgOrg", owner_phone="+919000700099",
        owner_email=f"wasc-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="SignupCfgBranch", status="active",
        whatsapp_number=f"+9178{str(uuid.uuid4().int)[:9]}",
    )
    db.add(branch)
    await db.commit()
    return org, branch


def _url(branch):
    return f"/branches/{branch.id}/whatsapp/signup-config"


@pytest.mark.asyncio
async def test_owner_gets_what_the_popup_needs(client, db, monkeypatch):
    org, branch = await _clinic(db)
    monkeypatch.setattr(settings, "meta_app_id", "1234567890")
    monkeypatch.setattr(settings, "meta_config_id", "9876543210")
    monkeypatch.setattr(settings, "meta_app_secret", "server-only-secret")
    monkeypatch.setattr(settings, "meta_webhook_verify_token", "verify-token")
    monkeypatch.setattr(settings, "meta_graph_version", "v25.0")

    r = await client.get(_url(branch), headers={
        "Authorization": "Bearer " + _jwt(
            role="org_admin", org_id=str(org.id), branch_ids=[str(branch.id)]
        )
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["app_id"] == "1234567890"
    assert body["config_id"] == "9876543210"
    assert body["configured"] is True
    assert body["graph_version"] == "v25.0"
    assert body["feature_type"] == "whatsapp_business_app_onboarding"
    assert set(body["required_permissions"]) == {
        "whatsapp_business_management", "whatsapp_business_messaging",
    }


@pytest.mark.asyncio
async def test_the_app_secret_never_leaves_the_server(client, db, monkeypatch):
    """RULE 9. The secret is what lets a token be minted from the code; if it
    reached the browser, anyone could mint clinic tokens."""
    org, branch = await _clinic(db)
    monkeypatch.setattr(settings, "meta_app_id", "111")
    monkeypatch.setattr(settings, "meta_config_id", "222")
    monkeypatch.setattr(settings, "meta_app_secret", "SUPER-SECRET-VALUE")

    r = await client.get(_url(branch), headers={
        "Authorization": "Bearer " + _jwt(
            role="org_admin", org_id=str(org.id), branch_ids=[str(branch.id)]
        )
    })
    assert "SUPER-SECRET-VALUE" not in r.text
    assert "app_secret" not in r.text


@pytest.mark.asyncio
async def test_unconfigured_reports_itself_instead_of_opening_a_doomed_popup(
    client, db, monkeypatch
):
    org, branch = await _clinic(db)
    monkeypatch.setattr(settings, "meta_app_id", "111")
    monkeypatch.setattr(settings, "meta_config_id", "")

    r = await client.get(_url(branch), headers={
        "Authorization": "Bearer " + _jwt(
            role="org_admin", org_id=str(org.id), branch_ids=[str(branch.id)]
        )
    })
    assert r.status_code == 200
    assert r.json()["configured"] is False


@pytest.mark.asyncio
async def test_a_receptionist_cannot_read_it(client, db):
    """Connecting the clinic's WhatsApp identity is an owner-level decision,
    same bar as telephony and billing."""
    org, branch = await _clinic(db)
    r = await client.get(_url(branch), headers={
        "Authorization": "Bearer " + _jwt(
            role="staff", org_id=str(org.id), branch_ids=[str(branch.id)]
        )
    })
    assert r.status_code == 403, r.text


@pytest.mark.asyncio
async def test_another_clinics_owner_cannot_read_it(client, db):
    """RULE 1: branch scoping holds even for an owner-role token."""
    _org_a, branch_a = await _clinic(db)
    org_b, branch_b = await _clinic(db)
    r = await client.get(_url(branch_a), headers={
        "Authorization": "Bearer " + _jwt(
            role="org_admin", org_id=str(org_b.id), branch_ids=[str(branch_b.id)]
        )
    })
    assert r.status_code in (403, 404), r.text


@pytest.mark.asyncio
async def test_anonymous_is_rejected(client, db):
    _org, branch = await _clinic(db)
    r = await client.get(_url(branch))
    assert r.status_code in (401, 403)


def test_preflight_required_fields_match_the_runbook():
    """scripts/wa_preflight.py hardcodes the six webhook fields it demands.

    That list also lives in the onboarding runbook, and the two drifting apart
    is the exact failure the script exists to prevent: a field nobody
    subscribed silently drops a whole class of event (no `messages` = no
    patient reaches the bot). Pin them to each other.
    """
    import re
    from pathlib import Path

    from scripts.wa_preflight import REQUIRED_FIELDS

    runbook = Path("docs/runbooks/META_WHATSAPP_SETUP.md").read_text(encoding="utf-8")
    section = runbook.split("## 3. Configure the webhook", 1)[1].split("##", 1)[0]
    documented = set(re.findall(r"^- `([a-z_]+)`$", section, re.MULTILINE))

    assert documented, "runbook section 3 no longer lists the subscribed fields"
    assert REQUIRED_FIELDS == documented
