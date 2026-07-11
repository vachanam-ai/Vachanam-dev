"""Proof for the fault-tolerance primitives (backend/services/resilience.py):
timeout, circuit breaker open/half-open/recover, chaos injection (gated),
retries, fallback, and metrics. Pure unit — no DB/Redis."""
import asyncio
import time

import pytest

from backend.config import settings
from backend.services import resilience as R

pytestmark = pytest.mark.asyncio


@pytest.fixture(autouse=True)
def _reset():
    """Module state is process-global; clear it before each test."""
    R._breakers.clear()
    R._metrics.clear()
    R._chaos.clear()
    yield
    R._breakers.clear()
    R._metrics.clear()
    R._chaos.clear()


async def _ok():
    return "ok"


async def _boom():
    raise RuntimeError("dependency down")


async def _slow():
    await asyncio.sleep(1.0)
    return "late"


async def test_success_records_metrics():
    out = await R.guard("dep", _ok, timeout=1)
    assert out == "ok"
    snap = R._metric("dep").snapshot()
    assert snap["ok"] == 1 and snap["total"] == 1 and snap["error_rate"] == 0.0


async def test_timeout_counts_and_returns_fallback():
    out = await R.guard("dep", _slow, timeout=0.05, fallback="fb")
    assert out == "fb"
    assert R._metric("dep").snapshot()["timeout"] == 1


async def test_failure_reraises_without_fallback():
    with pytest.raises(RuntimeError):
        await R.guard("dep", _boom, timeout=1)
    assert R._metric("dep").snapshot()["failed"] == 1


async def test_breaker_opens_then_rejects_instantly():
    # Drive FAIL_THRESHOLD failures → breaker opens.
    for _ in range(R.FAIL_THRESHOLD):
        await R.guard("dep", _boom, timeout=1, fallback=None)
    assert R._breaker("dep").state() == "open"

    # Next call is rejected WITHOUT touching the dependency (rejected_open++),
    # and _boom is never entered (would raise) — fallback returns cleanly.
    before = R._metric("dep").failed
    out = await R.guard("dep", _boom, timeout=1, fallback="rejected")
    assert out == "rejected"
    m = R._metric("dep").snapshot()
    assert m["rejected_open"] == 1
    assert R._metric("dep").failed == before  # dependency was NOT called


async def test_breaker_half_opens_and_recovers():
    for _ in range(R.FAIL_THRESHOLD):
        await R.guard("dep", _boom, timeout=1, fallback=None)
    # Fast-forward past the reset window instead of sleeping 30s.
    R._breaker("dep").opened_at = time.monotonic() - R.RESET_AFTER - 1
    # Half-open probe succeeds → breaker closes.
    out = await R.guard("dep", _ok, timeout=1)
    assert out == "ok"
    assert R._breaker("dep").state() == "closed"


async def test_retries_then_succeeds():
    calls = {"n": 0}

    async def _flaky():
        calls["n"] += 1
        if calls["n"] < 3:
            raise RuntimeError("transient")
        return "recovered"

    out = await R.guard("dep", _flaky, timeout=1, retries=3, backoff=0.001)
    assert out == "recovered" and calls["n"] == 3


async def test_chaos_is_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "chaos_enabled", False)
    R.set_chaos("dep", fail_rate=1.0)  # would fail every call IF applied
    out = await R.guard("dep", _ok, timeout=1)
    assert out == "ok"  # chaos ignored because the flag is off (prod safety)


async def test_chaos_injects_failure_when_enabled(monkeypatch):
    monkeypatch.setattr(settings, "chaos_enabled", True)
    R.set_chaos("dep", fail_rate=1.0)
    out = await R.guard("dep", _ok, timeout=1, fallback="fb")
    assert out == "fb"  # forced failure → fallback
    assert R._metric("dep").snapshot()["failed"] == 1


async def test_chaos_injects_latency_and_trips_timeout(monkeypatch):
    monkeypatch.setattr(settings, "chaos_enabled", True)
    R.set_chaos("dep", latency_ms=200)
    out = await R.guard("dep", _ok, timeout=0.05, fallback="fb")
    assert out == "fb"  # injected 200ms delay > 50ms timeout
    assert R._metric("dep").snapshot()["timeout"] == 1


async def test_board_shape():
    await R.guard("dep", _ok, timeout=1)
    b = R.board()
    assert b["chaos_enabled"] in (True, False)
    assert "dep" in b["dependencies"]
    assert b["dependencies"]["dep"]["circuit"] == "closed"
