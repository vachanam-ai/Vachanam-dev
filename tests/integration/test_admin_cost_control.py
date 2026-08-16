import uuid
from datetime import datetime, timedelta, timezone

import httpx
import jwt
import pytest

from backend.config import settings
from backend.models.schema import Branch, CallLog, CallQuality, Organization
from backend.services.cost_control import RATE_VERSION, measured_ai_cost_inr


def _headers():
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "owner@vachanam.in",
            "role": "super_admin",
            "org_id": None,
            "branch_ids": [],
            "is_admin": True,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_owner_cost_control_is_per_clinic_measured_and_contains_no_pii(db, redis):
    org = Organization(
        name="Metered Clinic",
        owner_phone="+919000000001",
        owner_email=f"metered-{uuid.uuid4().hex[:6]}@example.com",
        plan="solo",
        status="active",
    )
    db.add(org)
    await db.flush()
    branch = Branch(
        org_id=org.id,
        name="Main",
        whatsapp_number=f"+9188{uuid.uuid4().int % 10**8:08d}",
        did_number=f"+9177{uuid.uuid4().int % 10**8:08d}",
        status="active",
    )
    db.add(branch)
    await db.flush()
    now = datetime.now(timezone.utc)
    db.add(
        CallLog(
            branch_id=branch.id,
            call_type="inbound",
            caller_last4="7554",
            answered=True,
            started_at=now,
            duration_seconds=61,
            booking_made=False,
        )
    )
    raw = dict(
        stt_audio_seconds=20.0,
        tts_audio_seconds=25.0,
        llm_prompt_tokens=10_000,
        llm_cached_tokens=8_000,
        llm_completion_tokens=500,
    )
    db.add(
        CallQuality(
            branch_id=branch.id,
            session_id="privacy-safe-session",
            call_type="inbound_info",
            duration_seconds=61,
            turns=2,
            transcript="patient: my secret complaint",
            usage_rate_version=RATE_VERSION,
            measured_ai_cost_inr=measured_ai_cost_inr(**raw),
            **raw,
        )
    )
    await db.commit()

    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/admin/cost-control", headers=_headers())
    assert response.status_code == 200, response.text
    payload = response.json()
    row = next(item for item in payload["clinics"] if item["org_id"] == str(org.id))
    assert row["cdr_minutes"] == pytest.approx(1.02, abs=0.01)
    assert row["billed_minutes"] == 2
    assert row["telemetry_coverage_pct"] == 100.0
    assert row["llm_cached_tokens"] == 8000
    assert row["estimated_gap_cost_inr"] == 0
    assert row["measured_ai_cost_inr"] > 0
    assert {card["key"] for card in payload["providers"]} >= {
        "soniox", "gemini", "vobiz", "livekit", "fly", "render", "supabase", "upstash", "cloudflare"
    }
    assert "my secret complaint" not in response.text
    assert "7554" not in response.text


@pytest.mark.asyncio
async def test_cost_control_rejects_clinic_admin(redis):
    now = datetime.now(timezone.utc)
    token = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "email": "clinic@example.com",
            "role": "org_admin",
            "org_id": str(uuid.uuid4()),
            "branch_ids": [],
            "is_admin": False,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(hours=1)).timestamp()),
            "jti": str(uuid.uuid4()),
        },
        settings.jwt_secret,
        algorithm="HS256",
    )
    from backend.main import app

    transport = httpx.ASGITransport(app=app, client=("testclient", 123))
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/admin/cost-control", headers={"Authorization": f"Bearer {token}"}
        )
    assert response.status_code == 403
