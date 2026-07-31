"""Graceful DB-read-failure speech (2026-07-31). When a read tool's DB
connection fails outright (pooler breaker / outage) even after run_db_read's
retries, the agent must speak a fixed warm line and stop — never let the LLM
improvise a raw "unable to fetch data from database" at the patient. Fully
kill-switched behind voice_db_failure_grace (default OFF).
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import UUID

import pytest
from livekit.agents import StopResponse

from agent.livekit_minimal import agent as agent_module
from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.system_prompt import DoctorContext
from agent.session_state import SessionState

BRANCH_ID = UUID("2e6d5a8a-30f0-4a90-9a9c-000000000006")


class _RecordingSession:
    def __init__(self):
        self.spoken = []

    def say(self, text, **kwargs):
        self.spoken.append((text, kwargs))


def _agent():
    return VachanamAgent(
        instructions="unused",
        state=SessionState(branch_id=BRANCH_ID, branch_timezone="Asia/Kolkata", language="en"),
        db=object(), room=None, calendar_service=None, meta_service=None,
        transfer_to="", lang_code="en",
        doctor_facts=[DoctorContext(
            id="1", name="Dr. Ravi", specialization="skin",
            routing_keywords=["skin"], booking_type="appointment", is_default=True,
        )],
    )


def test_flag_defaults_on():
    """Vinay directive: a caller must never hear a raw DB error, so the grace
    path is ON by default (kill-switch kept for rollback)."""
    from backend.config import settings

    assert settings.voice_db_failure_grace is True


def test_guard_speaks_and_stops_when_grace_on(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_db_failure_grace", True)
    monkeypatch.setattr(agent_module, "AgentSession", _RecordingSession)
    session = _RecordingSession()
    agent = _agent()
    ctx = SimpleNamespace(session=session)

    # ConnectionError is transient per is_transient_database_error
    with pytest.raises(StopResponse):
        agent._stop_on_db_read_failure(ctx, ConnectionError("pooler breaker"))
    assert len(session.spoken) == 1
    assert "try again" in session.spoken[0][0].lower()
    # never leaks a raw technical phrase
    assert "database" not in session.spoken[0][0].lower()


def test_guard_is_noop_when_grace_off(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_db_failure_grace", False)
    monkeypatch.setattr(agent_module, "AgentSession", _RecordingSession)
    session = _RecordingSession()
    agent = _agent()
    ctx = SimpleNamespace(session=session)

    # no raise, nothing spoken → caller re-raises the original error (today's behaviour)
    agent._stop_on_db_read_failure(ctx, ConnectionError("pooler breaker"))
    assert session.spoken == []


def test_guard_ignores_non_transient_error(monkeypatch):
    """A ToolError / ValueError (a real data/logic condition, not an outage)
    must pass straight through — never swallowed by the grace path."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_db_failure_grace", True)
    monkeypatch.setattr(agent_module, "AgentSession", _RecordingSession)
    session = _RecordingSession()
    agent = _agent()
    ctx = SimpleNamespace(session=session)

    agent._stop_on_db_read_failure(ctx, ValueError("bad doctor id"))
    assert session.spoken == []


def test_guard_is_noop_off_a_live_session(monkeypatch):
    """A simulation/test context (not an AgentSession) keeps the raise-through
    behaviour so unit tests and the returned-dict path are unaffected."""
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_db_failure_grace", True)
    monkeypatch.setattr(agent_module, "AgentSession", _RecordingSession)
    agent = _agent()
    # context.session is NOT a _RecordingSession (the patched AgentSession type)
    ctx = SimpleNamespace(session=object())
    agent._stop_on_db_read_failure(ctx, ConnectionError("pooler breaker"))  # no raise


def test_read_tools_wrap_db_reads_with_the_guard():
    """The booking-critical read tools must route a DB outage through the guard
    (not let it escape to the LLM as a raw error)."""
    for name in (
        "check_availability", "find_my_bookings", "get_queue_status",
        "route_to_doctor",
    ):
        src = inspect.getsource(getattr(VachanamAgent, name))
        assert "_stop_on_db_read_failure" in src, name
