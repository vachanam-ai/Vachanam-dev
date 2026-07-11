"""Day-12 trial payment nudge (real-payments wiring, 2026-07-11).

Contracts:
  * a trial ending within 2 days gets exactly ONE email (Redis nx dedup)
  * a trial with >2 days left, or already paused, is never nudged
  * email failure never raises (RULE 8)
"""
import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

import backend.jobs.trial_pause as job
from backend.config import settings
from backend.models.schema import Organization


class _FakeRedis:
    def __init__(self):
        self.store = {}

    async def set(self, k, v, ex=None, nx=False):
        if nx and k in self.store:
            return None  # redis-py returns None when NX fails
        self.store[k] = v
        return True


class _FakeResp:
    status_code = 200


class _FakeHttp:
    sent = []

    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def post(self, url, headers=None, json=None):
        _FakeHttp.sent.append(json)
        return _FakeResp()


async def _seed_trial(db, *, days_left: float, status="trial"):
    org = Organization(
        id=uuid.uuid4(), name="Nudge Clinic",
        owner_phone=f"+9190{str(uuid.uuid4().int)[:8]}",
        owner_email=f"own-{uuid.uuid4().hex[:6]}@t.com",
        plan="clinic", status=status,
        trial_ends_at=datetime.now(timezone.utc) + timedelta(days=days_left),
    )
    db.add(org)
    await db.commit()
    return org


@pytest.mark.asyncio
async def test_nudge_sent_once_for_ending_trial(db, monkeypatch):
    org = await _seed_trial(db, days_left=1)
    _FakeHttp.sent = []
    fake_r = _FakeRedis()
    monkeypatch.setattr(settings, "resend_api_key", "test-key")
    with patch("backend.redis_client.get_redis", return_value=fake_r), \
         patch("httpx.AsyncClient", _FakeHttp):
        await job.run_trial_nudge()
        await job.run_trial_nudge()  # second run: deduped, no second email
    mine = [m for m in _FakeHttp.sent if m["to"] == [org.owner_email]]
    assert len(mine) == 1
    assert "trial ends" in mine[0]["subject"]
    assert "/settings#plan" in mine[0]["text"]


@pytest.mark.asyncio
async def test_no_nudge_when_trial_far_or_not_trial(db, monkeypatch):
    far = await _seed_trial(db, days_left=10)
    paused = await _seed_trial(db, days_left=1, status="paused")
    _FakeHttp.sent = []
    monkeypatch.setattr(settings, "resend_api_key", "test-key")
    with patch("backend.redis_client.get_redis", return_value=_FakeRedis()), \
         patch("httpx.AsyncClient", _FakeHttp):
        await job.run_trial_nudge()
    targets = [m["to"][0] for m in _FakeHttp.sent]
    assert far.owner_email not in targets
    assert paused.owner_email not in targets
