"""FIXLOG #299 — Postgres must sleep when there is no work.

Neon suspends compute only after 5 min of total query silence (not shortenable),
so a 30-60s poller pinned it awake 24/7: ~$19/mo at 0.25 CU with zero calls.
That exhausted the plan on 2026-07-09 and took the clinic offline.

wake_gate answers "must I touch Postgres?" from Redis alone. The contract that
matters: it FAILS OPEN. A missed reminder costs a patient their appointment; an
extra query costs a fraction of a cent.
"""
import time
from unittest.mock import patch

import pytest

from backend.jobs import wake_gate


class _FakeRedis:
    """Minimal async-context-manager Redis stand-in."""

    def __init__(self, store=None, boom=False):
        self.store = store if store is not None else {}
        self.boom = boom

    async def __aenter__(self):
        if self.boom:
            raise ConnectionError("redis down")
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, k):
        if self.boom:
            raise ConnectionError("redis down")
        return self.store.get(k)

    async def set(self, k, v):
        self.store[k] = str(v)

    async def delete(self, k):
        self.store.pop(k, None)

    async def exists(self, k):
        return 1 if k in self.store else 0


def _patch(fake):
    return patch.object(wake_gate, "_redis", lambda: fake)


# ── the safety contract: fail open ──────────────────────────────────────────
@pytest.mark.asyncio
async def test_scheduled_runs_when_redis_is_down():
    with _patch(_FakeRedis(boom=True)):
        assert await wake_gate.should_run_scheduled("reminders") is True


@pytest.mark.asyncio
async def test_scheduled_runs_when_key_missing():
    """Unknown next-due time ⇒ ask Postgres, never assume 'nothing to do'."""
    with _patch(_FakeRedis({})):
        assert await wake_gate.should_run_scheduled("reminders") is True


# ── the saving: skip Postgres when nothing is due ───────────────────────────
@pytest.mark.asyncio
async def test_scheduled_skips_before_due_time():
    store = {"wake:next_at:reminders": str(time.time() + 600)}
    with _patch(_FakeRedis(store)):
        assert await wake_gate.should_run_scheduled("reminders") is False


@pytest.mark.asyncio
async def test_scheduled_runs_at_due_time():
    store = {"wake:next_at:reminders": str(time.time() - 1)}
    with _patch(_FakeRedis(store)):
        assert await wake_gate.should_run_scheduled("reminders") is True


@pytest.mark.asyncio
async def test_set_next_at_caps_at_safety_ceiling():
    """No job may sleep past the ceiling — a stale due time self-heals."""
    fake = _FakeRedis({})
    with _patch(fake):
        await wake_gate.set_next_at("reminders", time.time() + 10 * 86400)
    parked = float(fake.store["wake:next_at:reminders"])
    assert parked <= time.time() + wake_gate.SAFETY_SECONDS + 2


@pytest.mark.asyncio
async def test_set_next_at_none_means_recheck_within_ceiling():
    fake = _FakeRedis({})
    with _patch(fake):
        await wake_gate.set_next_at("reminders", None)
    parked = float(fake.store["wake:next_at:reminders"])
    assert time.time() < parked <= time.time() + wake_gate.SAFETY_SECONDS + 2


@pytest.mark.asyncio
async def test_clear_next_at_forces_a_db_pass():
    """A new/moved booking invalidates the parked time."""
    fake = _FakeRedis({"wake:next_at:reminders": str(time.time() + 600)})
    with _patch(fake):
        assert await wake_gate.should_run_scheduled("reminders") is False
        await wake_gate.clear_next_at("reminders")
        assert await wake_gate.should_run_scheduled("reminders") is True


# ── never let the keepalive come back ───────────────────────────────────────
def test_db_keepalive_is_gone_and_not_started():
    """#285's keepalive pinged every 3 min purely to defeat Neon's 5-min
    scale-to-zero. It IS the 24/7 cost. It must not return."""
    import inspect

    import agent.livekit_minimal.agent as ag

    src = inspect.getsource(ag)
    assert "_start_db_keepalive" not in src
    assert "_keepalive_dsn" not in src
    # the render (HTTP) keepalive is unrelated and must survive
    assert "_start_render_keepalive()" in src
