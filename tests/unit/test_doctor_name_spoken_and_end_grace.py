"""Two live-call fixes (Vinay 2026-07-31):

1. end_call must not hang up on a caller who speaks right after the goodbye —
   a short grace window aborts the hangup if they start talking.
2. A doctor's name must reach TTS in the call language's script (RULE 6) so it
   is pronounced natively, not read as Latin with an English accent.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest
from livekit.agents import ToolError  # noqa: F401  (import guard)

from agent.livekit_minimal import agent as agent_module
from agent.livekit_minimal.agent import VachanamAgent
from agent.livekit_minimal.grounded_turns import doctor_roster_reply
from agent.prompts.grounded_prompt import _doctor_rows
from agent.prompts.system_prompt import DoctorContext
from agent.session_state import SessionState

BRANCH_ID = UUID("2e6d5a8a-30f0-4a90-9a9c-000000000006")


# ── issue 2: doctor name rendered in the call script for TTS ──────────────────

def test_doctor_rows_speak_the_script_name_when_present():
    docs = [DoctorContext(
        id="1", name="Dr. Ravi Kumar", name_spoken="డాక్టర్ రవి కుమార్",
        specialization="skin", routing_keywords=["skin"],
        booking_type="appointment", is_default=True,
    )]
    row = _doctor_rows(docs)
    assert "డాక్టర్ రవి కుమార్" in row       # spoken (Telugu) name is what the LLM says
    assert 'name="Dr. Ravi Kumar"' not in row  # the Latin spelling is not in the roster


def test_doctor_rows_fall_back_to_latin_when_no_spoken_name():
    docs = [DoctorContext(
        id="1", name="Dr. Ravi", specialization="skin",
        routing_keywords=["skin"], booking_type="appointment", is_default=True,
    )]
    assert 'name="Dr. Ravi"' in _doctor_rows(docs)


def test_roster_reply_speaks_script_name():
    docs = [DoctorContext(
        id="1", name="Dr. Ravi", name_spoken="డాక్టర్ రవి",
        specialization="skin", routing_keywords=["skin"],
        booking_type="appointment", is_default=True,
    )]
    reply = doctor_roster_reply("which doctors do you have", "te", docs)
    assert reply is not None
    assert "డాక్టర్ రవి" in reply
    assert "Dr. Ravi" not in reply


# ── issue 1: end_call grace window ────────────────────────────────────────────

class _Session:
    def __init__(self, user_state):
        self.user_state = user_state


def _agent():
    return VachanamAgent(
        instructions="unused",
        state=SessionState(branch_id=BRANCH_ID, branch_timezone="Asia/Kolkata", language="te"),
        db=object(), room=SimpleNamespace(name="room-1"), calendar_service=None,
        meta_service=None, transfer_to="", lang_code="te",
        doctor_facts=[DoctorContext(
            id="1", name="Dr. Ravi", specialization="skin",
            routing_keywords=["skin"], booking_type="appointment", is_default=True,
        )],
    )


@pytest.mark.asyncio
async def test_end_call_aborts_when_caller_speaks_after_goodbye(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_end_call_grace", True)
    monkeypatch.setattr(settings, "voice_end_call_grace_seconds", 0.3)
    monkeypatch.setattr(agent_module, "AgentSession", _Session)

    def _boom(*_a, **_k):  # tearing the room down would be a bug here
        raise AssertionError("hung up on a talking caller")

    monkeypatch.setattr(agent_module.api, "LiveKitAPI", _boom)

    agent = _agent()
    session = _Session(user_state="speaking")
    ctx = SimpleNamespace(session=session, wait_for_playout=AsyncMock())
    result = await agent.end_call(ctx)

    assert result["success"] is False
    assert result["aborted"] == "caller_spoke"


@pytest.mark.asyncio
async def test_end_call_hangs_up_when_caller_stays_silent(monkeypatch):
    from backend.config import settings

    monkeypatch.setattr(settings, "voice_end_call_grace", True)
    monkeypatch.setattr(settings, "voice_end_call_grace_seconds", 0.2)
    monkeypatch.setattr(agent_module, "AgentSession", _Session)

    deleted = {}

    class _Room:
        async def delete_room(self, req):
            deleted["room"] = getattr(req, "room", None)

    class _Api:
        def __init__(self):
            self.room = _Room()

        async def aclose(self):
            return None

    monkeypatch.setattr(agent_module.api, "LiveKitAPI", _Api)
    monkeypatch.setattr(
        agent_module.api, "DeleteRoomRequest", lambda room: SimpleNamespace(room=room)
    )

    agent = _agent()
    session = _Session(user_state="listening")  # silent → proceed to hang up
    ctx = SimpleNamespace(session=session, wait_for_playout=AsyncMock())
    result = await agent.end_call(ctx)

    assert result["success"] is True
    assert deleted["room"] == "room-1"
