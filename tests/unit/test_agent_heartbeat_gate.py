"""#411: the agent's watchdog beacon must mean "registered with LiveKit and
able to take calls", not merely "process alive". 2026-07-19: a booted-but-
never-registered worker heartbeated for 4 hours while the line was dead —
inbound unanswerable and a doctor_advice follow-up dispatched into an empty
room. Gate = a logging filter on the SDK's own 'livekit.agents' logger:
"registered worker" sets the flag, drain/shutdown clears it. While unset the
beacon is withheld, so the existing 180s-stale watchdog auto-restart fires."""
import logging
import threading

import agent.livekit_minimal.agent as agent_mod
from agent.livekit_minimal.agent import _LkRegistrationWatch


def _record(msg: str) -> logging.LogRecord:
    return logging.LogRecord("livekit.agents", logging.INFO, __file__, 1, msg, (), None)


def setup_function(_):
    agent_mod._lk_registered = threading.Event()


def test_registration_line_sets_flag():
    watch = _LkRegistrationWatch()
    assert not agent_mod._lk_registered.is_set()
    assert watch.filter(_record("registered worker")) is True  # never swallows the record
    assert agent_mod._lk_registered.is_set()


def test_plugin_registered_does_not_set_flag():
    # "plugin registered" fires at boot BEFORE the worker connects — must not count
    _LkRegistrationWatch().filter(_record("plugin registered"))
    assert not agent_mod._lk_registered.is_set()


def test_drain_and_shutdown_clear_flag():
    watch = _LkRegistrationWatch()
    # LK-5: the SDK's reconnect warning = silent WebSocket drop — without
    # clearing, a stale flag kept the beacon alive while the line was dead.
    for closer in ("draining worker", "shutting down worker",
                   "failed to connect to livekit, retrying in 2s"):
        agent_mod._lk_registered.set()
        watch.filter(_record(closer))
        assert not agent_mod._lk_registered.is_set(), closer


def test_heartbeat_mirrors_registration_truth_to_redis():
    # LK-4: state key written EVERY tick (registered or not) — the health
    # board's lossless truth, independent of Fly logs; the beacon stays gated.
    import inspect

    src = inspect.getsource(agent_mod._start_watchdog_heartbeat)
    assert "watchdog:lk:agent_state" in src
    assert src.index("watchdog:lk:agent_state") < src.index("watchdog:hb:agent")
    assert "if registered:" in src  # beacon still conditional


def test_filter_never_raises_on_weird_record():
    rec = logging.LogRecord("livekit.agents", logging.INFO, __file__, 1, "%s %s", ("one",), None)
    assert _LkRegistrationWatch().filter(rec) is True  # broken args → swallowed, record passes


def test_heartbeat_source_gated_on_registration():
    # Source guard: the Redis write sits behind the registration flag.
    import inspect

    src = inspect.getsource(agent_mod._start_watchdog_heartbeat)
    assert "_lk_registered.is_set()" in src
    assert src.index("_lk_registered.is_set()") < src.index("watchdog:hb:agent")
