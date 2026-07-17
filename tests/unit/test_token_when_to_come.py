"""assign_token must GROUND when the patient should come (Vinay real call
2026-07-17 03:00: token 1 assigned at night, agent said 'come now itself';
the doctor sits from morning). The tool now returns queue_open_now +
when_to_come so the LLM never improvises."""
import uuid
from datetime import date, datetime, time, timedelta

import pytest

from backend.models.schema import Branch, Doctor, Organization
from agent.tools import booking_tools


async def _seed(db, start=time(10, 0), end=time(13, 0)):
    org = Organization(name="TokOrg", owner_phone="+919000700093",
                       owner_email=f"tok-{uuid.uuid4().hex[:6]}@test.com",
                       plan="clinic", status="active")
    db.add(org)
    await db.flush()
    b = Branch(org_id=org.id, name="TokBranch",
               whatsapp_number=f"+9199{str(uuid.uuid4().int)[:8]}", status="active")
    db.add(b)
    await db.flush()
    d = Doctor(branch_id=b.id, name="Dr Token", booking_type="token",
               daily_token_limit=50, status="active",
               working_hours_start=start, working_hours_end=end)
    db.add(d)
    await db.commit()
    return b, d


def _freeze_branch_now(monkeypatch, b, at: time):
    async def _fake_branch_now(branch_id, db):
        return datetime.combine(date.today(), at)
    monkeypatch.setattr(booking_tools, "_branch_now", _fake_branch_now)


@pytest.mark.asyncio
async def test_night_token_says_doctor_hours_not_come_now(db, redis, monkeypatch):
    b, d = await _seed(db)
    _freeze_branch_now(monkeypatch, b, time(3, 0))  # 3 AM call
    r = await booking_tools.assign_token(d.id, b.id, date.today(), db)
    assert r["success"] is True and r["token_number"] >= 1
    assert r["queue_open_now"] is False
    assert "NEVER say 'come now'" in r["when_to_come"]
    assert "10:00" in r["when_to_come"]  # states when the doctor starts


@pytest.mark.asyncio
async def test_daytime_token_queue_running(db, redis, monkeypatch):
    b, d = await _seed(db)
    _freeze_branch_now(monkeypatch, b, time(11, 0))  # inside sitting hours
    r = await booking_tools.assign_token(d.id, b.id, date.today(), db)
    assert r["success"] is True
    assert r["queue_open_now"] is True
    assert "come right away" in r["when_to_come"]


@pytest.mark.asyncio
async def test_future_date_token_never_open_now(db, redis, monkeypatch):
    b, d = await _seed(db)
    _freeze_branch_now(monkeypatch, b, time(11, 0))
    r = await booking_tools.assign_token(d.id, b.id, date.today() + timedelta(days=2), db)
    assert r["success"] is True
    assert r["queue_open_now"] is False  # tomorrow's queue is not running today


@pytest.mark.asyncio
async def test_unconfigured_hours_no_time_promise(db, redis, monkeypatch):
    b, d = await _seed(db, start=None, end=None)
    _freeze_branch_now(monkeypatch, b, time(3, 0))
    r = await booking_tools.assign_token(d.id, b.id, date.today(), db)
    assert r["success"] is True
    assert r["queue_open_now"] is False
    assert "not configured" in r["when_to_come"]
