"""A logged call's minutes surface on the owner dashboard (analytics overview).

Proves the metering -> dashboard path the owner sees as "Voice minutes this
month": a finalized CallLog (as the agent writes it) is summed by
/analytics/overview into minutes.used.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
from jose import jwt

from backend.config import settings
from backend.models.schema import Branch, CallLog, Organization

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _owner_jwt(org_id, branch_id):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": "owner@min.test", "role": "org_admin",
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
        name="Min Org", owner_phone="+919000555001",
        owner_email=f"min-{uuid.uuid4().hex[:6]}@test.com", plan="solo", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="Min Branch",
        whatsapp_number=f"+9155{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    await db.commit()
    return {"org_id": str(org.id), "branch_id": str(b.id), "bid": b.id}


async def test_logged_call_minutes_show_on_dashboard(branch, client, db):
    bid = branch["branch_id"]
    # Two finalized calls this month: 180s + 240s = 420s = 7 minutes.
    now = datetime.now(timezone.utc)
    db.add_all([
        CallLog(branch_id=branch["bid"], call_type="inbound", answered=True,
                started_at=now, duration_seconds=180, booking_made=True),
        CallLog(branch_id=branch["bid"], call_type="inbound", answered=True,
                started_at=now, duration_seconds=240, booking_made=False),
    ])
    await db.commit()

    r = await client.get(
        "/analytics/overview",
        params={"branch_id": bid, "days": 14},
        headers={"Authorization": f"Bearer {_owner_jwt(branch['org_id'], bid)}"},
    )
    assert r.status_code == 200, r.text
    minutes = r.json()["minutes"]
    assert minutes["used"] == 7          # 420s // 60
    assert minutes["included"] == 100    # solo plan allowance
