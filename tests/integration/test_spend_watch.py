"""Spend thresholds notify. They never block a call.

Vinay 2026-08-12: "Budget caps/alerts for everything so bymistake something
leaks we will not get hurt too much." Asked on 2026-08-13 whether to hard-block
a runaway, he chose ALERT ONLY — no paying clinic is ever cut off on spend.

So the single most important assertion in this file is the negative one:
running the watcher changes NOTHING about whether calls are served.
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from backend.jobs import spend_watch
from backend.jobs.spend_watch import (
    RUNAWAY_MULTIPLE,
    WARN_MULTIPLE,
    _breach,
    run_spend_watch,
)
from backend.models.schema import BillingCycle, Branch, CallLog, Organization


# ── the threshold decision, in isolation ──────────────────────────────────

def test_normal_usage_is_silent():
    assert _breach(0, 1500) is None
    assert _breach(1499, 1500) is None
    assert _breach(1500, 1500) is None, "using the bucket you bought is not an alert"


def test_warn_and_runaway_multiples():
    assert _breach(1500 * WARN_MULTIPLE, 1500) == "warn"
    assert _breach(1500 * RUNAWAY_MULTIPLE, 1500) == "runaway"


def test_runaway_outranks_warn():
    """A 10x blowout must not be reported as a mild warning."""
    assert _breach(15_000, 1500) == "runaway"


def test_a_plan_with_no_included_minutes_has_no_bucket_to_exceed():
    """The `wa` plan buys no voice at all — dividing by it would raise."""
    assert _breach(0, 0) is None
    assert _breach(500, 0) is None


# ── against the database ──────────────────────────────────────────────────

async def _org(
    db: AsyncSession, *, plan: str = "clinic", status: str = "active"
) -> Organization:
    org = Organization(
        id=uuid.uuid4(), name="Runaway Clinic", plan=plan, status=status,
        owner_phone=f"+9198{uuid.uuid4().int % 100000000:08d}",
        owner_email=f"{uuid.uuid4().hex[:10]}@example.com",
    )
    db.add(org)
    await db.flush()
    return org


async def _cycle(db: AsyncSession, org: Organization, *, included: int = 1500):
    today = date.today()
    cycle = BillingCycle(
        id=uuid.uuid4(), org_id=org.id,
        cycle_start=today - timedelta(days=10),
        cycle_end=today + timedelta(days=20),
        plan=org.plan, base_amount=10999, included_minutes=included,
    )
    db.add(cycle)
    await db.flush()
    return cycle


async def _burn(db: AsyncSession, org: Organization, minutes: int):
    branch = Branch(
        id=uuid.uuid4(), org_id=org.id, name="Main", timezone="Asia/Kolkata",
        address="A", whatsapp_number=f"+9198{uuid.uuid4().int % 100000000:08d}",
    )
    db.add(branch)
    await db.flush()
    db.add(
        CallLog(
            id=uuid.uuid4(), branch_id=branch.id, call_type="inbound",
            started_at=datetime.now(timezone.utc) - timedelta(days=1),
            duration_seconds=minutes * 60,
        )
    )
    await db.flush()
    return branch


@pytest.fixture
def alerts(monkeypatch):
    fired: list[dict] = []

    async def _capture(**kw):
        fired.append(kw)
        return True

    monkeypatch.setattr(
        "backend.services.ops_alert.send_ops_alert", _capture
    )
    return fired


@pytest.mark.asyncio
async def test_a_runaway_clinic_alerts(db: AsyncSession, alerts):
    org = await _org(db)
    await _cycle(db, org, included=1500)
    await _burn(db, org, 5000)  # >3x
    await db.commit()

    await run_spend_watch()

    assert len(alerts) == 1
    assert alerts[0]["event"] == "spend.runaway"


@pytest.mark.asyncio
async def test_normal_usage_never_alerts(db: AsyncSession, alerts):
    org = await _org(db)
    await _cycle(db, org, included=1500)
    await _burn(db, org, 900)
    await db.commit()

    await run_spend_watch()

    assert alerts == []


@pytest.mark.asyncio
async def test_the_alert_never_blocks_a_call(db: AsyncSession, alerts):
    """THE point of alert-only. The watcher must not touch billing state."""
    from backend.services.billing_math import call_blocked

    org = await _org(db)
    await _cycle(db, org, included=1500)
    await _burn(db, org, 9000)  # 6x — as bad as it gets
    await db.commit()

    await run_spend_watch()
    await db.refresh(org)

    assert alerts, "the runaway did not even alert"
    assert org.hard_block_on_exhaust is False, "the watcher flipped a blocking switch"
    assert org.status == "active", "the watcher changed org status"
    assert call_blocked(
        org.status, org.plan, org.hard_block_on_exhaust, 9000
    ) is None, "a call would now be refused on spend"


@pytest.mark.asyncio
async def test_the_dedupe_key_is_per_org_per_cycle_per_level(db: AsyncSession, alerts):
    """An hourly job must not mail the same standing condition every hour."""
    org = await _org(db)
    cycle = await _cycle(db, org, included=1500)
    await _burn(db, org, 5000)
    await db.commit()

    await run_spend_watch()

    key = alerts[0]["dedupe_key"]
    assert str(org.id) in key
    assert str(cycle.cycle_start) in key
    assert "runaway" in key


@pytest.mark.asyncio
async def test_a_paused_org_is_not_watched(db: AsyncSession, alerts):
    """call_blocked already stops these, so minutes cannot accrue — alerting
    on them would be noise."""
    org = await _org(db, status="paused")
    await _cycle(db, org, included=1500)
    await _burn(db, org, 9000)
    await db.commit()

    await run_spend_watch()

    assert alerts == []


@pytest.mark.asyncio
async def test_an_org_with_no_billing_cycle_is_skipped(db: AsyncSession, alerts):
    """Nothing billed yet means no cycle window to measure against."""
    org = await _org(db)
    await _burn(db, org, 9000)
    await db.commit()

    await run_spend_watch()

    assert alerts == []


@pytest.mark.asyncio
async def test_one_broken_org_does_not_stop_the_others(
    db: AsyncSession, alerts, monkeypatch
):
    """RULE 8 at the job level."""
    good = await _org(db)
    await _cycle(db, good, included=1500)
    await _burn(db, good, 5000)
    await db.commit()

    calls = {"n": 0}
    real = spend_watch._cycle_minutes

    async def _explode_once(db_, org_id, start, end):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("transient")
        return await real(db_, org_id, start, end)

    monkeypatch.setattr(spend_watch, "_cycle_minutes", _explode_once)

    other = await _org(db)
    await _cycle(db, other, included=1500)
    await _burn(db, other, 5000)
    await db.commit()

    await run_spend_watch()  # must not raise

    assert len(alerts) >= 1, "one failing org swallowed every other alert"
