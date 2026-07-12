"""Super-admin platform monitoring endpoint (/admin/monitoring).

- Aggregates call_quality + judge scores across ALL clinics for super_admin.
- Per-clinic rollup uses clinic NAME (org-level) — no patient data.
- NEVER leaks transcript text or judge_summary (RULE 1: super_admin out of PII).
- Requires is_admin; a normal owner is 403.
"""
import uuid
from datetime import datetime, timedelta, timezone

import httpx
import pytest
import pytest_asyncio
import jwt

from backend.config import settings
from backend.models.schema import Branch, CallQuality, Organization

pytestmark = pytest.mark.asyncio
_ALGO = "HS256"


def _jwt(role, is_admin):
    now = datetime.now(timezone.utc)
    return jwt.encode(
        {
            "sub": str(uuid.uuid4()), "email": f"{role}@mon.test", "role": role,
            "org_id": None, "branch_ids": [], "is_admin": is_admin,
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
async def seeded(db):
    org = Organization(
        name="Mon Org", owner_phone="+919000888001",
        owner_email=f"mon-{uuid.uuid4().hex[:6]}@t.com", plan="clinic", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="Mon Clinic A",
        whatsapp_number=f"+9188{str(uuid.uuid4().int)[:8]}", status="active",
    )
    db.add(b)
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add_all([
        CallQuality(branch_id=b.id, language="te", duration_seconds=120, turns=5,
                    booking_made=True, judge_score=5, judge_tags=["good"],
                    judge_summary="clean", created_at=now),
        CallQuality(branch_id=b.id, language="te", duration_seconds=60, turns=2,
                    booking_abandoned=True, fail_reason="abandoned_hold",
                    judge_score=2, judge_tags=["misrouted"],
                    judge_summary="SECRET internal note", created_at=now),
    ])
    await db.commit()
    return b


async def test_monitoring_aggregates_for_super_admin(seeded, client):
    r = await client.get(
        "/admin/monitoring", params={"days": 14},
        headers={"Authorization": f"Bearer {_jwt('super_admin', True)}"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["total_calls"] >= 2
    assert body["booked"] >= 1
    assert body["judged"] >= 2
    assert body["avg_judge_score"] is not None
    # per-clinic rollup carries the clinic NAME (org-level, allowed)
    assert any(c["name"] == "Mon Clinic A" for c in body["by_clinic"])
    # issue-tag frequencies aggregated
    tags = {t["tag"] for t in body["tag_frequencies"]}
    assert "misrouted" in tags or "good" in tags
    # PII / internal guard: judge_summary text must NEVER cross this boundary
    assert "SECRET internal note" not in r.text
    assert "transcript" not in body  # no transcript field at all


async def test_b23_daily_trend_buckets_in_ist(seeded, client, db):
    """B23: a call at 02:00 IST on a PAST day (which is the previous UTC calendar
    day) must land on that IST day's bucket, not the UTC-previous day (which is
    05:30 off from every other IST series). Uses an isolated past day so the
    fixture's same-day rows don't mask the boundary."""
    from zoneinfo import ZoneInfo

    ist = ZoneInfo("Asia/Kolkata")
    ist_day = (datetime.now(ist) - timedelta(days=3)).date()
    created_ist = datetime(ist_day.year, ist_day.month, ist_day.day, 2, 0, tzinfo=ist)
    created_utc = created_ist.astimezone(timezone.utc)
    utc_day = created_utc.date()
    assert utc_day != ist_day  # sanity: 02:00 IST is the previous UTC day

    db.add(CallQuality(
        branch_id=seeded.id, language="te", duration_seconds=42, turns=1,
        booking_made=True, created_at=created_utc,
    ))
    await db.commit()

    r = await client.get(
        "/admin/monitoring", params={"days": 14},
        headers={"Authorization": f"Bearer {_jwt('super_admin', True)}"},
    )
    assert r.status_code == 200, r.text
    daily = {row["date"]: row for row in r.json()["daily"]}
    assert daily.get(ist_day.isoformat(), {}).get("calls", 0) >= 1, (
        "IST-early call must bucket onto its IST day"
    )
    # and NOT on the UTC-previous day (the old, wrong bucket)
    assert daily.get(utc_day.isoformat(), {}).get("calls", 0) == 0, (
        "call must not appear under the UTC-previous-day bucket"
    )


async def test_monitoring_blocks_non_admin(client):
    r = await client.get(
        "/admin/monitoring", params={"days": 14},
        headers={"Authorization": f"Bearer {_jwt('org_admin', False)}"},
    )
    assert r.status_code == 403, r.text
