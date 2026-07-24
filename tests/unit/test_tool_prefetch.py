"""#5 tool prefetch — parallel doctor-routing on high-confidence booking intent.

On a booking turn the slow first tool (route_to_doctor: LLM match + DB read) is
fired in parallel with the reply LLM, on a DEDICATED session (never sharing the
call's self._db across coroutines) and strictly branch-scoped (RULE 1). The
route_to_doctor tool consumes the prefetched result; a stale prefetch is
cancelled on the next turn (leaks bounded to <=1 task). Kill switch:
VOICE_TOOL_PREFETCH.
"""
from __future__ import annotations

import asyncio
import types

import agent.livekit_minimal.agent as ag


def _bare_agent(monkeypatch, *, doctor_id=None):
    """A VachanamAgent with just the fields the prefetch path touches (skips the
    heavy __init__)."""
    a = ag.VachanamAgent.__new__(ag.VachanamAgent)
    a._state = types.SimpleNamespace(branch_id="branch-1", doctor_id=doctor_id, complaint=None)
    a._db = object()
    a._prefetch_route = None
    a._prefetch_complaint = ""
    monkeypatch.setattr(ag.settings, "voice_tool_prefetch", True, raising=False)
    return a


def _stub_routing(monkeypatch, calls, *, delay=0.0, result=None):
    async def fake_route(**kw):
        if delay:
            await asyncio.sleep(delay)
        calls.append(kw)
        return result if result is not None else {"doctor_id": None, "candidates": []}

    class _CM:
        async def __aenter__(self):
            return "prefetch-db"

        async def __aexit__(self, *a):
            return False

    monkeypatch.setattr(ag, "route_to_doctor", fake_route)
    monkeypatch.setattr(ag, "AsyncSessionLocal", lambda: _CM())


# ── intent classifier ───────────────────────────────────────────────────────
def test_is_booking_intent_telugu_and_english():
    assert ag._is_booking_intent("నాకు డాక్టర్ అపాయింట్‌మెంట్ కావాలి")
    assert ag._is_booking_intent("I need a doctor appointment for tooth pain")
    assert ag._is_booking_intent("పంటి నొప్పి ఉంది, చూపించాలి")


def test_is_booking_intent_rejects_chitchat():
    assert not ag._is_booking_intent("హలో")
    assert not ag._is_booking_intent("thank you")
    assert not ag._is_booking_intent("")


# ── prefetch fires on a dedicated, branch-scoped session ────────────────────
async def test_prefetch_fires_on_booking_intent(monkeypatch):
    a = _bare_agent(monkeypatch)
    calls: list = []
    _stub_routing(monkeypatch, calls)

    a._maybe_prefetch_routing("I need a doctor for tooth pain")
    assert a._prefetch_route is not None
    await a._prefetch_route  # let it run

    assert len(calls) == 1
    assert calls[0]["db"] == "prefetch-db"          # dedicated session, not self._db
    assert calls[0]["branch_id"] == "branch-1"       # RULE 1 branch scope


async def test_no_prefetch_without_intent_or_when_doctor_known(monkeypatch):
    a = _bare_agent(monkeypatch)
    calls: list = []
    _stub_routing(monkeypatch, calls)
    a._maybe_prefetch_routing("hello there")
    assert a._prefetch_route is None

    a2 = _bare_agent(monkeypatch, doctor_id="doc-x")  # routing already done
    a2._maybe_prefetch_routing("I need a doctor appointment")
    assert a2._prefetch_route is None


async def test_kill_switch_disables_prefetch(monkeypatch):
    a = _bare_agent(monkeypatch)
    monkeypatch.setattr(ag.settings, "voice_tool_prefetch", False, raising=False)
    calls: list = []
    _stub_routing(monkeypatch, calls)
    a._maybe_prefetch_routing("I need a doctor appointment for tooth pain")
    assert a._prefetch_route is None


# ── consumption ─────────────────────────────────────────────────────────────
async def test_consume_uses_prefetch_not_refetch(monkeypatch):
    a = _bare_agent(monkeypatch)
    calls: list = []
    _stub_routing(monkeypatch, calls, result={"doctor_id": "d1", "candidates": []})

    a._maybe_prefetch_routing("I need a doctor for tooth pain")
    # LLM extracts a subset complaint → consumes the in-flight prefetch
    result = await a._consume_or_route("tooth pain")
    assert result == {"doctor_id": "d1", "candidates": []}
    assert len(calls) == 1                 # prefetch only — no second (refetch) call
    assert a._prefetch_route is None       # cleared


async def test_consume_refetches_on_topic_change(monkeypatch):
    a = _bare_agent(monkeypatch)
    calls: list = []
    _stub_routing(monkeypatch, calls)

    a._maybe_prefetch_routing("I need a skin doctor for a rash")
    # unrelated complaint (not a subset either way) → drop stale, route fresh on self._db
    await a._consume_or_route("my tooth is broken")
    assert any(c["db"] is a._db for c in calls)   # a fresh route on the LIVE session
    assert a._prefetch_route is None              # stale prefetch dropped


# ── cancel-safety ───────────────────────────────────────────────────────────
async def test_stale_prefetch_cancelled_on_next_turn(monkeypatch):
    a = _bare_agent(monkeypatch)
    calls: list = []
    _stub_routing(monkeypatch, calls, delay=5.0)  # long-running so it stays pending

    a._maybe_prefetch_routing("I need a doctor appointment for tooth pain")
    first = a._prefetch_route
    assert first is not None

    a._maybe_prefetch_routing("actually I want a skin doctor for a rash")
    await asyncio.sleep(0)  # let the cancellation propagate
    assert first.cancelled() or first.done()      # old task cancelled
    assert a._prefetch_route is not None and a._prefetch_route is not first
    a._cancel_prefetch()  # cleanup
