"""A timings lookup must be about the doctor the caller is actually discussing.

LIVE 2026-08-12 (session call-b4e18d37aa5b790fc559): the caller was routed to
Dr Srinivas for jaw pain, then asked "is he there on Saturday?". The agent
answered "Dr Srinivas's timings for August 15 are not published yet".

Proven against production data on the same day: Srinivas is `recurring` and
sits 9:00-12:00 and 5:00-9:00 PM that Saturday, so `status="unpublished"` is
unreachable for him. The only doctor on that roster it IS reachable for is
vishnu vardhan reddy (`schedule_mode="date_specific"`, published 13th + 14th
only) — so the lookup ran on a doctor the caller had never mentioned. The
prompt hands the model every doctor's UUID, so it can emit any of them.
"""
from __future__ import annotations

import inspect
import uuid

import pytest

from agent.livekit_minimal import agent as ag


class _Doc:
    def __init__(self, did, name, specialization):
        self.id = did
        self.name = name
        self.specialization = specialization
        self.routing_keywords = []
        self.booking_type = "appointment"
        self.is_default = False


SRINIVAS = uuid.uuid4()
LAKSHMI = uuid.uuid4()
VISHNU = uuid.uuid4()
ROSTER = [
    _Doc(SRINIVAS, "Srinivas", "Dental"),
    _Doc(LAKSHMI, "Lakshmi", "Skin Specialist"),
    _Doc(VISHNU, "vishnu vardhan reddy", "children specialist"),
]


class _State:
    def __init__(self, doctor_id, utterance):
        self.doctor_id = doctor_id
        self.last_user_utterance = utterance
        self.session_id = "call-test"


def _resolve(established, utterance, passed):
    """Exercise the real guard with a minimally-populated agent."""
    inst = object.__new__(ag.VachanamAgent)
    inst._state = _State(established, utterance)
    inst._doctor_contexts = ROSTER
    return ag.VachanamAgent._established_doctor_or(inst, passed)


def test_the_live_failure_is_blocked():
    """"is he there on Saturday?" names nobody — keep Srinivas."""
    assert _resolve(SRINIVAS, "శనివారం బుక్ చేస్తారా?", VISHNU) == SRINIVAS


def test_caller_naming_another_doctor_wins():
    assert _resolve(SRINIVAS, "డాక్టర్ లక్ష్మి గారి టైమింగ్స్ చెప్పండి", LAKSHMI) == LAKSHMI


def test_caller_asking_by_specialty_wins():
    assert _resolve(SRINIVAS, "what are the skin doctor's timings?", LAKSHMI) == LAKSHMI


def test_nothing_established_yet_passes_through():
    assert _resolve(None, "is he there on Saturday?", VISHNU) == VISHNU


def test_agreeing_argument_is_untouched():
    assert _resolve(SRINIVAS, "is he there on Saturday?", SRINIVAS) == SRINIVAS


@pytest.mark.asyncio
async def test_doctor_pinning_is_the_safe_default():
    """Every LLM-authored tool argument is untrusted and pinned by default."""
    inst = object.__new__(ag.VachanamAgent)
    inst._state = _State(SRINIVAS, "శనివారం బుక్ చేస్తారా?")
    inst._state.caller_named_doctor_id = None
    inst._doctor_contexts = ROSTER

    assert await ag.VachanamAgent._resolve_doctor_id(inst, str(VISHNU)) == SRINIVAS
    assert (
        await ag.VachanamAgent._resolve_doctor_id(
            inst, str(VISHNU), keep_established=False
        )
        == VISHNU
    )


def test_every_doctor_tool_inherits_the_safe_default():
    from pathlib import Path

    signature = inspect.signature(ag.VachanamAgent._resolve_doctor_id)
    assert signature.parameters["keep_established"].default is True

    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    for tool_name in (
        "check_availability",
        "get_doctor_return_availability",
        "get_doctor_schedule",
        "assign_token",
        "confirm_booking",
    ):
        body = src.split(f"async def {tool_name}", 1)[1].split("@function_tool", 1)[0]
        assert "_resolve_doctor_id(" in body, tool_name
        assert "keep_established=False" not in body, tool_name


def test_schedule_resolution_remains_provable_in_logs():
    from pathlib import Path

    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    body = src.split("async def get_doctor_schedule", 1)[1].split("@function_tool", 1)[0]
    assert "doctor_schedule_resolved" in body, "resolved doctor is not logged"


def test_prompt_answers_only_the_latest_question():
    from agent.prompts.grounded_prompt import build_grounded_prompt  # noqa: F401
    from pathlib import Path

    src = Path("agent/prompts/grounded_prompt.py").read_text(encoding="utf-8")
    assert "ANSWER THE QUESTION THE CALLER JUST ASKED, AND ONLY THAT ONE." in src
    assert "absorb it silently and answer the new question" in src
