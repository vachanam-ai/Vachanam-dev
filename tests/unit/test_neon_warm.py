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
