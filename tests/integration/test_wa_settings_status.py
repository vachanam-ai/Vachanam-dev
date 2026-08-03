"""WA MVP1 Task 8 — Settings exposes WhatsApp connection status, never a
token. `whatsapp_status` comes straight from `Branch.wa_status` (mm36);
`whatsapp_masked_number` is last-4 only and only once connected (RULE 9)."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio

from backend.config import settings
from backend.models.schema import Branch, Organization

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _auth(tok: str) -> dict:
    return {"Authorization": f"Bearer {tok}"}


def _owner_jwt(org_id: str, branch_id: str) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "owner@wa-settings.test", "role": "org_admin",
            "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


async def _clinic(db, **branch_kwargs):
    org = Organization(
        name="WA Settings Org", owner_phone="+919000700099",
        owner_email=f"wa-settings-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id, name="WA Settings Branch",
        whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", status="active",
        **branch_kwargs,
    )
    db.add(branch)
    await db.commit()
    return org, branch


async def test_settings_exposes_wa_status_never_the_token(client, db):
    org, branch = await _clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.get(f"/branches/{branch.id}/settings", headers=_auth(owner))
    assert r.status_code == 200, r.text
    assert r.json()["whatsapp_status"] in ("none", "connected", "disconnected", "error")
    assert "token" not in r.text.lower()


async def test_default_status_is_none_and_number_unmasked_until_connected(client, db):
    org, branch = await _clinic(db)
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.get(f"/branches/{branch.id}/settings", headers=_auth(owner))
    body = r.json()
    assert body["whatsapp_status"] == "none"
    assert body["whatsapp_masked_number"] is None


async def test_connected_status_exposes_only_the_last_4_digits(client, db):
    org, branch = await _clinic(
        db, wa_status="connected", wa_phone_number_id="123456789012",
        wa_token_enc="not-a-real-token-value-just-checking-it-never-leaks",
    )
    owner = _owner_jwt(str(org.id), str(branch.id))

    r = await client.get(f"/branches/{branch.id}/settings", headers=_auth(owner))
    body = r.json()
    assert body["whatsapp_status"] == "connected"
    assert body["whatsapp_masked_number"] == f"…{branch.whatsapp_number[-4:]}"
    assert branch.whatsapp_number[:-4] not in r.text  # never the full number
    assert "not-a-real-token-value" not in r.text     # never any token
