"""WA T9: admin WhatsApp linking + ratings summary isolation (RULE 1)."""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest
import pytest_asyncio

from backend.config import settings
from backend.models.schema import Branch, Organization, Rating

_ALGO = "HS256"


@pytest_asyncio.fixture
async def client(redis, db):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


def _auth(tok):
    return {"Authorization": f"Bearer {tok}"}


def _jwt(payload: dict) -> str:
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "t@t.test",
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()),
            "jti": str(uuid.uuid4()),
            **payload,
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


def _admin_jwt():
    return _jwt({"role": "super_admin", "is_admin": True,
                 "org_id": None, "branch_ids": []})


def _owner_jwt(org_id, branch_id):
    return _jwt({"role": "org_admin", "is_admin": False,
                 "org_id": org_id, "branch_ids": [branch_id]})


async def _clinic(db):
    org = Organization(
        name="LOrg", owner_phone="+919000700040",
        owner_email=f"lk-{uuid.uuid4().hex[:6]}@test.com", plan="clinic",
        status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="LBranch",
        whatsapp_number=f"+9133{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    await db.commit()
    return org, b


@pytest.mark.asyncio
async def test_admin_links_and_conflicts(client, db):
    _, b1 = await _clinic(db)
    _, b2 = await _clinic(db)
    admin = _admin_jwt()

    r = await client.patch(
        f"/admin/branches/{b1.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": "123456789012"},
    )
    assert r.status_code == 200, r.text

    # same id on another branch → 409
    r2 = await client.patch(
        f"/admin/branches/{b2.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": "123456789012"},
    )
    assert r2.status_code == 409

    # non-numeric rejected
    r3 = await client.patch(
        f"/admin/branches/{b2.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": "abc"},
    )
    assert r3.status_code == 422

    # clear
    r4 = await client.patch(
        f"/admin/branches/{b1.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": None},
    )
    assert r4.status_code == 200 and r4.json()["wa_phone_number_id"] is None


@pytest.mark.asyncio
async def test_admin_links_waba_id_so_templates_can_be_created(client, db, monkeypatch):
    """Without wa_waba_id a branch can SEND but wa_template_admin refuses every
    submission (NotConnected) — the concierge path has to set both."""
    _, b1 = await _clinic(db)
    _, b2 = await _clinic(db)
    admin = _admin_jwt()

    r = await client.patch(
        f"/admin/branches/{b1.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": "111111111111", "wa_waba_id": "222222222222"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["wa_waba_id"] == "222222222222"

    # wa_template_admin can now resolve a WABA + token for this branch.
    # Bridge mode: no per-branch wa_token_enc, so token_for falls back to the
    # platform token — which is what the concierge/test-number path uses.
    from backend.services import wa_template_admin

    monkeypatch.setattr(settings, "meta_access_token", "EAA-test-token")
    await db.refresh(b1)
    waba, _token = wa_template_admin._waba_and_token(b1)
    assert waba == "222222222222"

    # unique — the same WABA on another branch is a clean 409, not a silent steal
    r2 = await client.patch(
        f"/admin/branches/{b2.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": "333333333333", "wa_waba_id": "222222222222"},
    )
    assert r2.status_code == 409

    # non-numeric rejected before any DB write
    r3 = await client.patch(
        f"/admin/branches/{b2.id}/whatsapp", headers=_auth(admin),
        json={"wa_waba_id": "not-an-id"},
    )
    assert r3.status_code == 422


@pytest.mark.asyncio
async def test_relinking_number_alone_keeps_the_waba(client, db):
    """Omitting wa_waba_id means 'unchanged' — a re-link of the phone number
    must not silently break template creation."""
    _, b = await _clinic(db)
    admin = _admin_jwt()
    await client.patch(
        f"/admin/branches/{b.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": "444444444444", "wa_waba_id": "555555555555"},
    )
    r = await client.patch(
        f"/admin/branches/{b.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": "666666666666"},
    )
    assert r.status_code == 200, r.text
    assert r.json()["wa_waba_id"] == "555555555555"


@pytest.mark.asyncio
async def test_unlinking_the_number_clears_the_waba(client, db):
    """wa_waba_id is UNIQUE: a stale one on a disconnected branch would 409 the
    clinic that actually owns it."""
    _, b = await _clinic(db)
    admin = _admin_jwt()
    await client.patch(
        f"/admin/branches/{b.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": "777777777777", "wa_waba_id": "888888888888"},
    )
    r = await client.patch(
        f"/admin/branches/{b.id}/whatsapp", headers=_auth(admin),
        json={"wa_phone_number_id": None},
    )
    assert r.status_code == 200, r.text
    assert r.json()["wa_waba_id"] is None


@pytest.mark.asyncio
async def test_owner_cannot_use_admin_link_endpoint(client, db):
    org, b = await _clinic(db)
    owner = _owner_jwt(str(org.id), str(b.id))
    r = await client.patch(
        f"/admin/branches/{b.id}/whatsapp", headers=_auth(owner),
        json={"wa_phone_number_id": "123456789012"},
    )
    assert r.status_code == 403


@pytest.mark.asyncio
async def test_ratings_summary_isolated_per_branch(client, db):
    org1, b1 = await _clinic(db)
    org2, b2 = await _clinic(db)
    db.add_all([
        Rating(branch_id=b1.id, score=5),
        Rating(branch_id=b1.id, score=1),
        Rating(branch_id=b2.id, score=3),
    ])
    await db.commit()

    o1 = _owner_jwt(str(org1.id), str(b1.id))
    r = await client.get(f"/branches/{b1.id}/ratings/summary", headers=_auth(o1))
    assert r.status_code == 200
    assert r.json() == {"avg": 3.0, "count": 2, "low_count": 1}

    # RULE 1: org1's owner cannot read org2's summary
    r2 = await client.get(f"/branches/{b2.id}/ratings/summary", headers=_auth(o1))
    assert r2.status_code in (403, 404)
