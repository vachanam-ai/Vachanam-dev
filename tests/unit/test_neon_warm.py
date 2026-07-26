"""Neon warm-keeper (#435 → #437 → ungated 2026-07-26).

A SELECT 1 under Neon's 5-min scale-to-zero holds the compute warm so the first
call after idle skips the ~2-4s cold wake. The interval MUST stay < 300s.

Two independent warmers, BOTH warming immediately on boot, so a master push
that restarts the agent AND the Render API at once cannot leave Neon cold
(Vinay live 2026-07-26, ~5s first reply):
  - API (Render): an unconditional per-instance loop in the FastAPI lifespan,
    NOT gated on the scheduler leader (a rolling redeploy's new instance is not
    the leader yet — that no-leader gap is exactly when Neon suspended).
  - Agent (Fly, always-on): the watchdog heartbeat pings on the FIRST tick and
    every 4th (~240s). #437: the API warmer alone is unreliable because Render
    free tier sleeps.
"""
import re
from pathlib import Path

_MAIN = Path("backend/main.py").read_text(encoding="utf-8")


def test_api_warmer_is_unconditional_not_leader_gated():
    # The loop is defined in the lifespan and started with create_task, NOT
    # registered as a scheduler job (which only the leader runs).
    assert "_neon_warm_loop" in _MAIN
    assert "neon_warm_task = asyncio.create_task(_neon_warm_loop())" in _MAIN
    assert "SELECT 1" in _MAIN
    # The old leader-gated job is gone — it left the no-leader deploy gap.
    assert 'id="keep_neon_warm"' not in _MAIN


def test_api_warm_interval_under_neon_sleep_threshold():
    loop = _MAIN.split("async def _neon_warm_loop")[1].split("neon_warm_task")[0]
    secs = int(re.findall(r"asyncio\.sleep\((\d+)\)", loop)[-1])
    assert secs <= 270, f"warm ping every {secs}s — must be < Neon's 300s sleep"


def test_api_warmer_cancelled_on_shutdown():
    assert "neon_warm_task.cancel()" in _MAIN


def test_agent_heartbeat_also_warms_neon_437():
    """#437: the #435 Render warm job failed because Render (free tier) sleeps
    and can't hold Neon awake. The agent (Fly) never sleeps, so its 60s
    heartbeat also pings Neon — on the FIRST tick (immediately after a restart,
    2026-07-26) and every 4th (~240s < Neon's 300s sleep)."""
    import inspect

    import agent.livekit_minimal.agent as ag

    hb = inspect.getsource(ag._start_watchdog_heartbeat)
    assert "_neon_tick % 4 == 0" in hb
    assert "_neon_tick == 1" in hb          # warms immediately on boot
    assert "SELECT 1" in hb
    assert "asyncpg" in hb
    assert "neon_warm_ping_failed" in hb   # never crashes the heartbeat
