"""FIXLOG #305 — one shared Redis client per event loop.

#299's fresh-client-per-call built a new rediss:// TLS client every 60s tick
x3 jobs (+ one per authenticated request in auth middleware). Render's 512MB
instance OOM-killed every ~2.5h from the day it shipped. The shared client
must be: cached (same object within a loop), loop-aware (new loop => new
client, no cross-loop reuse), and droppable (dead socket must not be reused).
"""
import asyncio

import pytest

import backend.redis_client as rc


@pytest.fixture(autouse=True)
def _reset():
    rc.drop()
    yield
    rc.drop()


@pytest.mark.asyncio
async def test_same_client_within_a_loop():
    a = rc.get_redis()
    b = rc.get_redis()
    assert a is b  # no per-call allocation — the whole point of #305


def test_new_loop_gets_new_client():
    """pytest/agent subprocesses create fresh loops (TD-016): a client bound
    to a dead loop must never be handed out again."""
    async def grab():
        return rc.get_redis()

    c1 = asyncio.run(grab())
    c2 = asyncio.run(grab())
    assert c1 is not c2


@pytest.mark.asyncio
async def test_drop_forces_rebuild():
    a = rc.get_redis()
    rc.drop()
    assert rc.get_redis() is not a


def test_wake_gate_uses_shared_client_not_fresh():
    """Guard: the 60s hammer must never go back to from_url per call."""
    import inspect

    import backend.jobs.wake_gate as wg
    import backend.middleware.auth_middleware as am

    assert "from_url" not in inspect.getsource(wg)
    assert "from_url" not in inspect.getsource(am)


def test_walkin_rollback_uses_shared_client_not_fresh():
    """SEC #3: the walk-in save-failure rollback must not build a per-call TLS
    client (the #305 OOM cause) — it uses redis_client.get_redis()."""
    import inspect

    import backend.routers.queue as q

    src = inspect.getsource(q.create_walkin)
    assert "from_url" not in src, "walk-in rollback regressed to per-call from_url"
    assert "get_redis" in src
