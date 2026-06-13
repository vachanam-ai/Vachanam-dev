"""Vobiz CDR sync → call_logs (authoritative call/minute metering).

Proves the agent-independent path: Vobiz call records are mapped DID→branch and
upserted into call_logs idempotently, so the dashboard's calls + minutes populate
even when the agent never wrote a row (dropped/crashed/local calls).
"""
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import func, select

from backend.models.schema import Branch, CallLog, Organization
from backend.services.vobiz_cdr import parse_call_record

pytestmark = pytest.mark.asyncio

DID = "+918045678901"


@pytest_asyncio.fixture
async def branch(db):
    org = Organization(
        name="CDR Org", owner_phone="+919000444001",
        owner_email=f"cdr-{uuid.uuid4().hex[:6]}@realclinic.in", plan="solo", status="active",
    )
    db.add(org)
    await db.flush()
    b = Branch(
        org_id=org.id, name="CDR Branch",
        whatsapp_number=f"+9144{str(uuid.uuid4().int)[:8]}",
        did_number=DID, status="active",
    )
    db.add(b)
    await db.commit()
    return {"bid": b.id}


def _records():
    now = datetime.now(timezone.utc)
    return [
        {"provider_call_id": "callA", "to_number": DID, "from_number": "+919666111222",
         "duration_seconds": 120, "started_at": now, "answered": True, "direction": "inbound"},
        {"provider_call_id": "callB", "to_number": DID, "from_number": "+919666333444",
         "duration_seconds": 240, "started_at": now, "answered": True, "direction": "inbound"},
        # Call on a DID we don't own → must be skipped (never cross-tenant).
        {"provider_call_id": "callC", "to_number": "+910000000000", "from_number": "+91999",
         "duration_seconds": 60, "started_at": now, "answered": True, "direction": "inbound"},
    ]


async def test_cdr_sync_creates_calllogs_mapped_to_branch(branch, db):
    from backend.jobs import vobiz_cdr_sync

    with patch.object(vobiz_cdr_sync, "fetch_recent_calls", AsyncMock(return_value=_records())):
        await vobiz_cdr_sync.run_vobiz_cdr_sync()

    rows = (
        await db.execute(select(CallLog).where(CallLog.branch_id == branch["bid"]))
    ).scalars().all()
    ids = {r.provider_call_id for r in rows}
    assert ids == {"callA", "callB"}          # callC (foreign DID) skipped
    assert sum(r.duration_seconds for r in rows) == 360  # 120 + 240
    assert all(r.answered for r in rows)


async def test_cdr_sync_idempotent_and_updates_duration(branch, db):
    from backend.jobs import vobiz_cdr_sync

    recs = _records()
    with patch.object(vobiz_cdr_sync, "fetch_recent_calls", AsyncMock(return_value=recs)):
        await vobiz_cdr_sync.run_vobiz_cdr_sync()
    # Vobiz finalizes callA's duration higher on a later sync.
    recs[0]["duration_seconds"] = 200
    with patch.object(vobiz_cdr_sync, "fetch_recent_calls", AsyncMock(return_value=recs)):
        await vobiz_cdr_sync.run_vobiz_cdr_sync()

    count = (
        await db.execute(
            select(func.count()).select_from(CallLog).where(
                CallLog.branch_id == branch["bid"]
            )
        )
    ).scalar_one()
    assert count == 2  # no duplicates despite two syncs

    callA = (
        await db.execute(select(CallLog).where(CallLog.provider_call_id == "callA"))
    ).scalar_one()
    assert callA.duration_seconds == 200  # updated, not duplicated


def test_parse_call_record_handles_plivo_field_variants():
    rec = parse_call_record({
        "call_uuid": "u1", "to_number": DID, "from_number": "+919666111222",
        "call_duration": "95", "answer_time": "2026-06-13 10:00:00",
        "call_direction": "inbound",
    })
    assert rec["provider_call_id"] == "u1"
    assert rec["duration_seconds"] == 95
    assert rec["answered"] is True
    assert rec["started_at"].tzinfo is not None
    # Missing UUID → unusable → None.
    assert parse_call_record({"to_number": DID}) is None
