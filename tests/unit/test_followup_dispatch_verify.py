"""#423: a follow-up dispatch only counts when a worker actually JOINED the
room. Three real calls were lost (2026-07-19 21:08 IST, 21:54 IST re-send,
2026-07-20 09:17 IST): create_dispatch succeeds even with NO registered
worker, so tasks were marked done while the room sat empty. Now an unclaimed
dispatch (no agent- participant within the timeout) deletes the room and
returns False → task stays pending → next 15-min tick retries."""
import asyncio
from types import SimpleNamespace
from uuid import uuid4

import pytest

import backend.jobs.next_visit_followup_caller as job


class _Parts:
    def __init__(self, identities):
        self.participants = [SimpleNamespace(identity=i) for i in identities]


class _FakeLk:
    """Mimics LiveKitAPI: dispatch always 'succeeds'; room join is scripted."""

    def __init__(self, joined_after_polls: int | None):
        # None = never joins; N = agent appears on the Nth poll
        self._joined_after = joined_after_polls
        self._polls = 0
        self.deleted_rooms: list[str] = []
        self.dispatches: list[str] = []
        outer = self

        class _AD:
            async def create_dispatch(self, req):
                outer.dispatches.append(req.room)
                return SimpleNamespace(id="AD_test")

        class _Room:
            async def list_participants(self, req):
                outer._polls += 1
                if outer._joined_after is not None and outer._polls >= outer._joined_after:
                    return _Parts(["agent-AJ_x", "sip_+91800"])
                return _Parts(["sip_+91800"])

            async def delete_room(self, req):
                outer.deleted_rooms.append(req.room)

        self.agent_dispatch = _AD()
        self.room = _Room()

    async def aclose(self):
        pass


def _task():
    return SimpleNamespace(id=uuid4(), task_type="doctor_advice", what_to_ask="q")


def _fixtures():
    branch = SimpleNamespace(id=uuid4())
    doctor = SimpleNamespace(id=uuid4(), name="Dr. X")
    patient = SimpleNamespace(phone="+918096007554", name="Vinay")
    return branch, doctor, patient


@pytest.fixture(autouse=True)
def fast_polls(monkeypatch):
    from backend.services import dispatch_verify

    monkeypatch.setattr(dispatch_verify, "JOIN_TIMEOUT_S", 0.2)
    monkeypatch.setattr(dispatch_verify, "JOIN_POLL_S", 0.05)
    monkeypatch.setattr(job, "branch_outbound_trunk_id", lambda b: "trunk-1")


def _run(fake):
    import unittest.mock as m

    branch, doctor, patient = _fixtures()
    # _dispatch does `from livekit import api as lk_api` — patch the real
    # module's constructor; the request classes are plain dataclasses and work.
    with m.patch("livekit.api.LiveKitAPI", lambda: fake):
        return asyncio.run(job._dispatch(_task(), branch, doctor, patient, None))


def test_agent_joins_marks_success():
    fake = _FakeLk(joined_after_polls=1)
    assert _run(fake) is True
    assert fake.deleted_rooms == []


def test_unclaimed_dispatch_returns_false_and_cleans_room(monkeypatch):
    # LK-3: an unclaimed dispatch is the definitive dead-line probe — it must
    # also trigger the watchdog's Fly restart (cooldown lives inside it).
    import backend.watchdog as wd

    restarts = []

    async def fake_restart():
        restarts.append(1)
        return "fly restart issued (test)"

    monkeypatch.setattr(wd, "_restart_fly_agent", fake_restart)
    fake = _FakeLk(joined_after_polls=None)
    assert _run(fake) is False           # → task stays pending, next tick retries
    assert fake.deleted_rooms == fake.dispatches  # empty room removed
    assert restarts == [1]               # auto-heal fired


def test_late_join_within_timeout_still_success():
    fake = _FakeLk(joined_after_polls=3)
    assert _run(fake) is True
