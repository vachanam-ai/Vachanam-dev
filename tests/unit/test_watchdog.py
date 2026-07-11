"""FIXLOG #306 — autonomous health watchdog.

Contracts that matter:
  * alerts fire on state CHANGE only (no email spam while a component stays down)
  * a stale/missing agent heartbeat triggers the Fly-restart remediation
  * the Fly restart honors its cooldown (no flap-restart loop on a broken deploy)
  * the 60s tick is Redis-only (never wakes Neon — #299 discipline)
  * a dead Redis cannot crash the tick (the watchdog itself must not be fragile)
"""
import json
import time
from unittest.mock import AsyncMock, patch

import pytest

import backend.watchdog as wd


class _FakeRedis:
    def __init__(self, store=None, boom=False):
        self.store = store if store is not None else {}
        self.boom = boom

    def _chk(self):
        if self.boom:
            raise ConnectionError("redis down")

    async def ping(self):
        self._chk()
        return True

    async def get(self, k):
        self._chk()
        return self.store.get(k)

    async def set(self, k, v, ex=None):
        self._chk()
        self.store[k] = str(v)

    async def exists(self, k):
        self._chk()
        return 1 if k in self.store else 0


@pytest.fixture(autouse=True)
def _reset_module_state():
    wd._redis_down_since = None
    wd._redis_down_notified = False
    yield


def _patched(fake, **extra):
    ps = [
        patch.object(wd, "get_redis", lambda: fake),
        patch.object(wd, "_email_alert", AsyncMock()),
        patch.object(wd, "_audit", AsyncMock()),
    ]
    for target, mock in extra.items():
        ps.append(patch.object(wd, target, mock))
    return ps


@pytest.mark.asyncio
async def test_transition_alerts_only_on_change():
    fake = _FakeRedis()
    email = AsyncMock()
    with patch.object(wd, "get_redis", lambda: fake), \
         patch.object(wd, "_email_alert", email), \
         patch.object(wd, "_audit", AsyncMock()):
        await wd._transition("agent", False, "down 1")
        await wd._transition("agent", False, "down 2")   # still down — no new mail
        await wd._transition("agent", True, "back")
    assert email.await_count == 2  # opened + resolved, never the repeat


@pytest.mark.asyncio
async def test_stale_heartbeat_triggers_fly_restart():
    fake = _FakeRedis({wd._AGENT_HB_KEY: str(time.time() - 999)})
    restart = AsyncMock(return_value="fly restart issued → m1:200")
    with patch.object(wd, "get_redis", lambda: fake), \
         patch.object(wd, "_email_alert", AsyncMock()), \
         patch.object(wd, "_audit", AsyncMock()), \
         patch.object(wd, "_restart_fly_agent", restart), \
         patch.object(wd, "process_mem_mb", lambda: None):
        await wd.run_watchdog_tick()
    restart.assert_awaited_once()
    state = json.loads(fake.store[wd._STATE_KEY.format(comp="agent")])
    assert state["status"] == "down"
    assert "fly restart" in state["action"]


@pytest.mark.asyncio
async def test_fresh_heartbeat_marks_agent_ok_no_restart():
    fake = _FakeRedis({wd._AGENT_HB_KEY: str(time.time() - 30)})
    restart = AsyncMock()
    with patch.object(wd, "get_redis", lambda: fake), \
         patch.object(wd, "_email_alert", AsyncMock()), \
         patch.object(wd, "_audit", AsyncMock()), \
         patch.object(wd, "_restart_fly_agent", restart), \
         patch.object(wd, "process_mem_mb", lambda: None):
        await wd.run_watchdog_tick()
    restart.assert_not_awaited()
    assert json.loads(fake.store[wd._STATE_KEY.format(comp="agent")])["status"] == "ok"


@pytest.mark.asyncio
async def test_fly_restart_cooldown_blocks_flap_loop():
    fake = _FakeRedis({wd._FLY_COOLDOWN_KEY: "1"})
    with patch.object(wd, "get_redis", lambda: fake), \
         patch.object(wd.settings, "fly_api_token", "tok"):
        msg = await wd._restart_fly_agent()
    assert "cooldown" in msg


@pytest.mark.asyncio
async def test_no_fly_token_means_alert_only():
    with patch.object(wd.settings, "fly_api_token", ""):
        msg = await wd._restart_fly_agent()
    assert "not configured" in msg


@pytest.mark.asyncio
async def test_redis_down_does_not_crash_and_emails_once():
    fake = _FakeRedis(boom=True)
    email = AsyncMock()
    with patch.object(wd, "get_redis", lambda: fake), \
         patch.object(wd, "_email_alert", email):
        await wd.run_watchdog_tick()
        await wd.run_watchdog_tick()   # second tick: still down, no second mail
    assert email.await_count == 1


class _FakeHttpClient:
    """Minimal httpx.AsyncClient stand-in for the Fly Machines API."""

    def __init__(self, machines):
        self.machines = machines
        self.restarted = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False

    async def get(self, url, headers=None):
        class R:
            def __init__(self, data):
                self._data = data

            def json(self):
                return self._data

        return R(self.machines)

    async def post(self, url, headers=None):
        self.restarted.append(url.rsplit("/machines/", 1)[1].split("/")[0])

        class R:
            status_code = 200

        return R()


@pytest.mark.asyncio
async def test_restart_skips_stopped_standby_when_a_machine_is_running():
    """FIXLOG #307: Fly exposes no standby flag — a hung-but-running primary
    must not drag the stopped standby awake (drill 2026-07-11 woke both)."""
    fake_http = _FakeHttpClient([
        {"id": "primary", "state": "started"},
        {"id": "standby", "state": "stopped"},
    ])
    with patch.object(wd, "get_redis", lambda: _FakeRedis()), \
         patch.object(wd.settings, "fly_api_token", "tok"), \
         patch.object(wd.httpx, "AsyncClient", lambda timeout: fake_http):
        msg = await wd._restart_fly_agent()
    assert fake_http.restarted == ["primary"]
    assert "primary:200" in msg


@pytest.mark.asyncio
async def test_restart_starts_exactly_one_machine_when_all_stopped():
    fake_http = _FakeHttpClient([
        {"id": "m1", "state": "stopped"},
        {"id": "m2", "state": "stopped"},
    ])
    with patch.object(wd, "get_redis", lambda: _FakeRedis()), \
         patch.object(wd.settings, "fly_api_token", "tok"), \
         patch.object(wd.httpx, "AsyncClient", lambda timeout: fake_http):
        await wd._restart_fly_agent()
    assert len(fake_http.restarted) == 1


def test_tick_never_imports_database():
    """#299 discipline: the 60s tick must be Redis-only. Only the hourly deep
    check may touch backend.database."""
    import inspect

    tick_src = inspect.getsource(wd.run_watchdog_tick)
    assert "database" not in tick_src
    assert "AsyncSessionLocal" not in tick_src
