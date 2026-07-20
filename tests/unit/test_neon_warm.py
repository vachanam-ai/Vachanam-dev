"""#435 (Vinay 2026-07-20: "very very serious about latency, fix it at any
cost"). The 14s call-start was Neon's scale-to-zero cold wake on the agent's
branch-resolve. A SELECT 1 kept-warm ping every 4 min holds the compute awake.

The interval MUST stay strictly under Neon's 5-minute sleep threshold, else
the DB sleeps between pings and the cold wake (the whole bug) returns. This
guards that invariant at the source, since the scheduler wiring lives in the
FastAPI lifespan and is awkward to exercise live.
"""
import re
from pathlib import Path

_MAIN = Path("backend/main.py").read_text(encoding="utf-8")


def test_keep_neon_warm_job_registered():
    assert "_keep_neon_warm" in _MAIN
    assert 'id="keep_neon_warm"' in _MAIN
    assert "SELECT 1" in _MAIN


def test_warm_interval_under_neon_sleep_threshold():
    # Find the IntervalTrigger seconds on the same add_job as keep_neon_warm.
    block = _MAIN.split("keep_neon_warm")[0]
    secs = int(re.findall(r"IntervalTrigger\(seconds=(\d+)\)", block)[-1])
    assert secs <= 270, f"warm ping every {secs}s — must be < Neon's 300s sleep"


def test_warms_immediately_on_boot():
    # next_run_time on boot so the first call after a deploy is already warm.
    assert "next_run_time=" in _MAIN.split("keep_neon_warm")[0].rsplit("add_job", 1)[-1] \
        or "next_run_time=_dt.now" in _MAIN


def test_agent_heartbeat_also_warms_neon_437():
    """#437: the #435 Render warm job failed because Render (free tier) sleeps
    and can't hold Neon awake. The agent (Fly) never sleeps, so its 60s
    heartbeat thread also pings Neon (every 4th tick, ~240s < Neon's 300s
    sleep). Guard that the ping lives in the heartbeat loop and is best-effort."""
    import inspect

    import agent.livekit_minimal.agent as ag

    hb = inspect.getsource(ag._start_watchdog_heartbeat)
    assert "_neon_tick % 4 == 0" in hb
    assert "SELECT 1" in hb
    assert "asyncpg" in hb
    assert "neon_warm_ping_failed" in hb   # never crashes the heartbeat
