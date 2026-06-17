"""The call_quality capture surfaces on the owner dashboard as aggregates.

Proves the monitoring path: agent-written CallQuality rows are summed by
/analytics/call-quality into conversion/abandon/transfer/turns — and that the
endpoint NEVER returns transcript text (PII stays internal) and is branch-scoped
(RULE 1: one clinic never sees another's calls).
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings
from backend.models.schema import Branch, CallQuality, Organization

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _owner_jwt(org_id, branch_id):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "owner@cq.test", "role": "org_admin",
            "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret, algorithm=_ALGO,
    )


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


@pytest_asyncio.fixture
async def branch(db):
    org = Organization(
        name="CQ Org", owner_phone="+919000666001",
        owner_email=f"cq-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="CQ Branch",
        whatsapp_number=f"+9166{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    # a SECOND branch in another org — its rows must never leak into the first's summary
    org2 = Organization(
        name="Other Org", owner_phone="+919000666002",
        owner_email=f"cq2-{uuid.uuid4().hex[:6]}@test.com", plan="clinic", status="active",
    )
    db.add(org2)
    await db.flush()
    b2 = Branch(
        org_id=org2.id, name="Other Branch",
        whatsapp_number=f"+9167{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b2)
    await db.commit()
    return {"org_id": str(org.id), "branch_id": str(b.id), "bid": b.id, "other_bid": b2.id}


async def test_call_quality_summary_aggregates(branch, client, db):
    now = datetime.now(timezone.utc)
    db.add_all([
        # 4 calls: 2 booked, 1 abandoned, 1 transfer; one out_of_scope failure
        CallQuality(branch_id=branch["bid"], language="te", duration_seconds=120, turns=5,
                    booking_made=True, created_at=now),
        CallQuality(branch_id=branch["bid"], language="te", duration_seconds=90, turns=3,
                    booking_made=True, created_at=now),
        CallQuality(branch_id=branch["bid"], language="hi", duration_seconds=60, turns=2,
                    booking_abandoned=True, fail_reason="abandoned_hold",
                    transcript="patient: secret health detail", created_at=now),
        CallQuality(branch_id=branch["bid"], language="te", duration_seconds=30, turns=1,
                    transfer_requested=True, fail_reason="out_of_scope", created_at=now),
        # other clinic's call — MUST NOT appear in this branch's summary (RULE 1)
        CallQuality(branch_id=branch["other_bid"], language="te", duration_seconds=999, turns=9,
                    booking_made=True, created_at=now),
    ])
    await db.commit()

    r = await client.get(
        "/analytics/call-quality",
        params={"branch_id": branch["branch_id"], "days": 14},
        headers={"Authorization": f"Bearer {_owner_jwt(branch['org_id'], branch['branch_id'])}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_calls"] == 4           # other clinic's row excluded (RULE 1)
    assert body["booked"] == 2
    assert body["conversion_rate"] == 0.5
    assert body["abandoned"] == 1
    assert body["transfers"] == 1
    assert body["by_language"] == {"te": 3, "hi": 1}
    reasons = {f["reason"]: f["count"] for f in body["failures"]}
    assert reasons == {"abandoned_hold": 1, "out_of_scope": 1}
    # PII GUARD: transcript text must never appear in the dashboard response
    assert "secret health detail" not in r.text


async def test_call_quality_requires_branch_access(branch, client):
    # A token for a different branch must not read this branch's quality.
    other = str(uuid.uuid4())
    r = await client.get(
        "/analytics/call-quality",
        params={"branch_id": branch["branch_id"], "days": 14},
        headers={"Authorization": f"Bearer {_owner_jwt(str(uuid.uuid4()), other)}"},
    )
    assert r.status_code in (401, 403), r.text
