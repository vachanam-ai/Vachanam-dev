"""DID cross-tenant hijack prevention.

A DID (the dialed number) is a clinic's identity — the voice agent resolves
which clinic's patients/doctors/calendar are touched purely from it. If two
branches could share a DID, a clinic could intercept another clinic's calls
(DPDP cross-tenant breach). The PATCH /branches/{id}/settings handler must
reject a DID already owned by a different branch.
"""
import uuid
from datetime import datetime, timezone, timedelta

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings
from backend.models.schema import Branch, Organization


def _make_jwt(role="org_admin", org_id=None, branch_ids=None):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(uuid.uuid4()),
        "email": f"did-test-{uuid.uuid4().hex[:6]}@test.com",
        "role": role,
        "org_id": org_id,
        "branch_ids": branch_ids or [],
        "is_admin": False,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(hours=settings.jwt_expire_hours)).timestamp()),
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _make_branch(db, *, did=None):
    org = Organization(
        name=f"DID Org {uuid.uuid4().hex[:6]}",
        owner_phone="+919100000000",
        owner_email=f"owner-{uuid.uuid4().hex[:6]}@test.com",
        plan="clinic",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="DID Branch",
        whatsapp_number=f"wa-{uuid.uuid4().hex[:10]}",
        did_number=did,
    )
    db.add(branch)
    await db.commit()
    await db.refresh(branch)
    return org, branch


@pytest.mark.asyncio
async def test_clinic_cannot_claim_another_clinics_did(client, db):
    """Clinic B saving Clinic A's DID -> 409, and B's DID stays unchanged."""
    _, branch_a = await _make_branch(db, did="+918000000001")
    org_b, branch_b = await _make_branch(db, did=None)

    token_b = _make_jwt(org_id=str(org_b.id), branch_ids=[str(branch_b.id)])
    r = await client.patch(
        f"/branches/{branch_b.id}/settings",
        json={"did_number": "+918000000001"},  # Clinic A's number
        headers={"Authorization": f"Bearer {token_b}"},
    )
    assert r.status_code == 409, r.text

    await db.refresh(branch_b)
    assert branch_b.did_number is None  # hijack did not take effect


@pytest.mark.asyncio
async def test_clinic_can_save_its_own_unique_did(client, db):
    """A free DID saves fine (idempotent re-save of own DID also OK)."""
    org, branch = await _make_branch(db, did=None)
    token = _make_jwt(org_id=str(org.id), branch_ids=[str(branch.id)])

    r = await client.patch(
        f"/branches/{branch.id}/settings",
        json={"did_number": "+918000009999"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 200, r.text

    # Re-saving the SAME number on the SAME branch must not 409 against itself
    r2 = await client.patch(
        f"/branches/{branch.id}/settings",
        json={"did_number": "+918000009999"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r2.status_code == 200, r2.text
