"""SEC #9 + #4 (2026-07-11 audit).

#9: a Google Calendar ID must belong to exactly one branch — otherwise clinic B
    could set clinic A's calendar_id and have its bookings written into A's
    calendar (cross-tenant PII spill via the shared service account).
#4: PII list endpoints carry a rate limiter (throttle bulk scraping).
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt

from backend.config import settings
from backend.models.schema import Branch, Organization

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _owner_jwt(org_id, branch_id):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {"sub": str(uuid.uuid4()), "email": "o@cal.test", "role": "org_admin",
         "org_id": org_id, "branch_ids": [branch_id], "is_admin": False,
         "iat": int(now.timestamp()),
         "exp": int((now + timedelta(hours=8)).timestamp()), "jti": str(uuid.uuid4())},
        settings.jwt_secret, algorithm=_ALGO)


@pytest_asyncio.fixture
async def client(redis):
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac


async def _clinic(db, tag, cal_id=None):
    org = Organization(name=f"O{tag}", owner_phone=f"+9190{str(uuid.uuid4().int)[:8]}",
                       owner_email=f"{tag}-{uuid.uuid4().hex[:5]}@t.com", plan="clinic",
                       status="active")
    db.add(org)
    await db.flush()
    b = Branch(org_id=org.id, name=f"B{tag}",
               whatsapp_number=f"+9158{str(uuid.uuid4().int)[:8]}", status="active",
               google_calendar_id=cal_id)
    db.add(b)
    await db.commit()
    return {"org_id": str(org.id), "branch_id": str(b.id)}


async def test_cannot_claim_another_clinics_calendar_id(client, db):
    await _clinic(db, "victim", cal_id="shared-cal@group.calendar.google.com")
    attacker = await _clinic(db, "attacker")
    tok = _owner_jwt(attacker["org_id"], attacker["branch_id"])
    r = await client.patch(
        f"/branches/{attacker['branch_id']}/settings",
        headers={"Authorization": f"Bearer {tok}"},
        json={"google_calendar_id": "shared-cal@group.calendar.google.com"},
    )
    assert r.status_code == 409, f"attacker claimed victim's calendar: {r.status_code}"


async def test_own_calendar_id_still_settable(client, db):
    c = await _clinic(db, "solo")
    tok = _owner_jwt(c["org_id"], c["branch_id"])
    r = await client.patch(
        f"/branches/{c['branch_id']}/settings",
        headers={"Authorization": f"Bearer {tok}"},
        json={"google_calendar_id": "my-own-cal@group.calendar.google.com"},
    )
    assert r.status_code == 200


def test_pii_list_endpoints_carry_rate_limiter():
    """#4: the patient/treatment/analytics GETs must be wired to a limiter so a
    stolen JWT can't bulk-scrape unthrottled."""
    from backend.main import app
    from backend.middleware.rate_limit import default_limit

    want = {
        "/patients/branches/{branch_id}/patients",
        "/treatment/branches/{branch_id}/treatment-patients",
        "/analytics/overview",
        "/analytics/call-quality",
    }
    seen = {}
    for route in app.routes:
        path = getattr(route, "path", None)
        if path in want:
            deps = getattr(getattr(route, "dependant", None), "dependencies", [])
            calls = [getattr(d, "call", None) for d in deps]
            seen[path] = default_limit in calls
    for p in want:
        assert seen.get(p), f"{p} is missing its rate limiter (#4)"
