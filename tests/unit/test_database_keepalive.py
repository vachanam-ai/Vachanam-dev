"""Supabase must not inherit Neon's retired scale-to-zero keepalive loops."""

import inspect
from pathlib import Path


def test_api_has_no_database_keepalive_loop():
    source = Path("backend/main.py").read_text(encoding="utf-8")
    assert "_neon_warm_loop" not in source
    assert "neon_warm_task" not in source


def test_agent_heartbeat_remains_redis_only():
    from agent.livekit_minimal.agent import _start_watchdog_heartbeat

    source = inspect.getsource(_start_watchdog_heartbeat)
    assert "SELECT 1" not in source
    assert "asyncpg" not in source
    assert "_neon_tick" not in source
