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


def test_pool_init_failures_clear_beacon_lk8():
    """LK-8 (2026-07-20 outage): a REGISTERED worker whose job-process pool is
    dead ('error initializing process' in a respawn loop) kept the beacon alive
    because the beacon was gated only on registration — the watchdog never
    restarted it and the line was dead for ~an hour. Now N pool-init errors in
    the window clear the same flag so the 180s auto-restart heals it."""
    import agent.livekit_minimal.agent as m

    m._lk_registered = threading.Event()
    m._lk_registered.set()          # worker is registered...
    m._proc_init_errs.clear()
    watch = _LkRegistrationWatch()

    # One transient init failure must NOT take the line down.
    watch.filter(_record("error initializing process"))
    assert m._lk_registered.is_set()

    # Reaching the threshold in-window clears the beacon.
    for _ in range(m._PROC_INIT_ERR_THRESHOLD):
        watch.filter(_record("error initializing process"))
    assert not m._lk_registered.is_set()


def test_reregistration_resets_pool_error_streak_lk8():
    import agent.livekit_minimal.agent as m

    m._lk_registered = threading.Event()
    m._proc_init_errs.clear()
    watch = _LkRegistrationWatch()

    for _ in range(m._PROC_INIT_ERR_THRESHOLD - 1):
        watch.filter(_record("error initializing process"))
    # A successful (re)registration wipes the streak → back to healthy.
    watch.filter(_record("registered worker"))
    assert m._lk_registered.is_set()
    assert m._proc_init_errs == []


def test_slow_drip_pool_failures_clear_beacon_lk8():
    """LK-8 slow-drip (2026-07-20 SECOND outage): the pool limped at ~1 error/
    min — never 3-in-120s, so the burst rule missed it and the line stayed dead
    until Vinay noticed. A sustained drip (>= drip threshold in the drip window)
    must also clear the beacon."""
    import agent.livekit_minimal.agent as m

    m._lk_registered = threading.Event()
    m._lk_registered.set()
    m._proc_init_errs.clear()
    watch = _LkRegistrationWatch()

    import time as _t
    base = _t.monotonic()
    # Errors spaced ~90s apart — never 3 inside 120s (no burst trip), but they
    # accumulate to the drip threshold inside the 10-min drip window.
    stamps = [base + i * 90 for i in range(m._PROC_INIT_DRIP_THRESHOLD)]
    orig = _t.monotonic
    try:
        for s in stamps:
            _t.monotonic = lambda s=s: s
            watch.filter(_record("error initializing process"))
    finally:
        _t.monotonic = orig
    assert not m._lk_registered.is_set()
