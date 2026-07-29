"""Release-blocking contracts for the 2026-07-29 production voice incident.

These tests exercise the turn dispatcher, not only the text helpers.  A
regression here must fail CI before the release/deploy job can run.
"""

import asyncio
from datetime import date, time
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID

import pytest
from livekit.agents import StopResponse

from agent.livekit_minimal import agent as agent_module
from agent.livekit_minimal.agent import VachanamAgent
from agent.livekit_minimal.confirm_speech import build_confirm_text
from agent.livekit_minimal.workflow_rules import (
    build_exact_availability_failure_text,
    build_mutation_failure_text,
)
from agent.prompts.system_prompt import DoctorContext
from agent.session_state import SessionState


BRANCH_ID = UUID("11ea4044-d99a-40d6-8925-5c3532bcc949")
SRINIVAS_ID = UUID("93f0f1ff-d567-47df-bd50-8df375af8519")
INCIDENT_DATE = date(2026, 7, 30)


class _RecordingSession:
    def __init__(self):
        self.spoken = []

    def say(self, text, **kwargs):
        self.spoken.append((text, kwargs))


def _message(text):
    return SimpleNamespace(text_content=text, content=text, role="user")


def _roster():
    return [
        DoctorContext(
            id="lakshmi",
            name="Dr. Lakshmi",
            specialization="Skin Specialist",
            routing_keywords=[],
            booking_type="appointment",
            is_default=False,
        ),
        DoctorContext(
            id=str(SRINIVAS_ID),
            name="Dr. Srinivas",
            specialization="Dental",
            routing_keywords=[],
            booking_type="appointment",
            is_default=False,
        ),
    ]


def _agent(state=None):
    state = state or SessionState(
        branch_id=BRANCH_ID,
        branch_timezone="Asia/Kolkata",
        language="en",
    )
    return VachanamAgent(
        instructions="unused by deterministic incident paths",
        state=state,
        db=object(),
        room=None,
        calendar_service=None,
        meta_service=None,
        transfer_to="",
        lang_code="en",
        doctor_names={SRINIVAS_ID: "Dr. Srinivas"},
        doctor_facts=_roster(),
    )


def _attach_session(monkeypatch, session):
    monkeypatch.setattr(
        VachanamAgent,
        "session",
        property(lambda _self: session),
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("question", "must_contain"),
    [
        ("is there any skin doctor with you?", "Dr. Lakshmi"),
        ("is there any orthopedic doctor?", "we do not have that specialist"),
    ],
)
async def test_specialist_questions_bypass_llm_database_and_slow_tools(
    monkeypatch, question, must_contain
):
    """The two incident questions are answered from the call-start DB snapshot.

    If control reaches routing/Gemini or availability I/O, this contract fails.
    """
    session = _RecordingSession()
    agent = _agent()
    _attach_session(monkeypatch, session)

    monkeypatch.setattr(
        agent,
        "_maybe_prefetch_routing",
        lambda _text: pytest.fail("specialist fact leaked to Gemini/tool routing"),
    )

    async def forbidden_availability(**_kwargs):
        pytest.fail("roster question performed an availability/database call")

    monkeypatch.setattr(agent_module, "check_availability", forbidden_availability)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message(question)
        )

    assert len(session.spoken) == 1
    assert must_contain in session.spoken[0][0]
    assert "ask the doctor" not in session.spoken[0][0].lower()


@pytest.mark.asyncio
async def test_correcting_730_to_7_forces_fresh_exact_1900_ground_truth(
    monkeypatch,
):
    """A corrected time may never reuse the previous 7:30 availability result."""
    state = SessionState(
        branch_id=BRANCH_ID,
        branch_timezone="Asia/Kolkata",
        language="en",
        last_availability_doctor_id=SRINIVAS_ID,
        last_availability_date=INCIDENT_DATE,
        last_availability_query_time=time(19, 30),
    )
    session = _RecordingSession()
    agent = _agent(state)
    _attach_session(monkeypatch, session)
    calls = []

    async def exact_availability(**kwargs):
        calls.append(kwargs)
        return "Dr. Srinivas is available 7:00 PM to 7:15 PM on 30 July."

    monkeypatch.setattr(agent_module, "check_availability", exact_availability)
    monkeypatch.setattr(
        agent,
        "_maybe_prefetch_routing",
        lambda _text: pytest.fail("fresh exact result leaked back to Gemini"),
    )

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message("No, I said 7")
        )

    assert len(calls) == 1
    assert calls[0]["doctor_id"] == SRINIVAS_ID
    assert calls[0]["branch_id"] == BRANCH_ID
    assert calls[0]["booking_date"] == INCIDENT_DATE
    assert calls[0]["query_start"] == time(19, 0)
    assert calls[0]["query_end"] == time(19, 0)
    assert state.last_availability_query_time == time(19, 0)
    assert len(session.spoken) == 1
    assert "available" in session.spoken[0][0]
    assert "7:00 PM" in session.spoken[0][0]


@pytest.mark.asyncio
async def test_unrenderable_availability_fails_closed_instead_of_guessing(
    monkeypatch,
):
    state = SessionState(
        branch_id=BRANCH_ID,
        branch_timezone="Asia/Kolkata",
        language="en",
        last_availability_doctor_id=SRINIVAS_ID,
        last_availability_date=INCIDENT_DATE,
        last_availability_query_time=time(19, 30),
    )
    session = _RecordingSession()
    agent = _agent(state)
    _attach_session(monkeypatch, session)

    async def ambiguous_result(**_kwargs):
        return "unexpected provider response"

    monkeypatch.setattr(agent_module, "check_availability", ambiguous_result)

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message("No, I said 7")
        )

    assert len(session.spoken) == 1
    assert "could not verify" in session.spoken[0][0].lower()
    assert "available" not in session.spoken[0][0].lower()


def test_booking_success_always_says_come_on_time_and_offers_more_help():
    spoken = build_confirm_text(
        "en",
        "booked_slot",
        date_=INCIDENT_DATE,
        time_=time(19, 0),
    )
    assert "Please come on time" in spoken
    assert "Is there anything else I can help you with?" in spoken


@pytest.mark.asyncio
async def test_short_no_after_booking_closes_without_an_llm_turn(monkeypatch):
    state = SessionState(
        branch_id=BRANCH_ID,
        language="en",
        awaiting_anything_else=True,
    )
    agent = _agent(state)
    closed = []

    async def fake_close():
        closed.append(True)

    monkeypatch.setattr(agent, "_handle_post_booking_close", fake_close)
    monkeypatch.setattr(
        agent,
        "_maybe_prefetch_routing",
        lambda _text: pytest.fail("post-booking close leaked to Gemini"),
    )

    with pytest.raises(StopResponse):
        await agent.on_user_turn_completed(
            SimpleNamespace(items=[]), _message("No, thanks")
        )
    await asyncio.sleep(0)

    assert closed == [True]
    assert state.awaiting_anything_else is False


def test_ci_blocks_release_on_these_contracts():
    workflow = (
        Path(__file__).resolve().parents[2] / ".github" / "workflows" / "ci.yml"
    ).read_text(encoding="utf-8")
    assert "pytest tests/ -q --tb=short" in workflow
    assert "needs: [lint, test, frontend, secret-scan]" in workflow


def test_rule_renderer_never_turns_unknown_outcome_into_success_or_failure():
    for language in ("te", "en", "hi"):
        text = build_mutation_failure_text(
            language,
            "book",
            {"success": False, "error": "booking_outcome_unverified"},
        )
        lowered = text.lower()
        assert text
        assert "booked" not in lowered
        assert "succeeded" not in lowered
        assert "cancelled" not in lowered


def test_rule_renderer_distinguishes_known_full_slot_from_unknown_outcome():
    full = build_mutation_failure_text(
        "en", "reserve", {"success": False, "reason": "full"}
    )
    unknown = build_mutation_failure_text(
        "en", "reserve", {"success": False, "error": "outcome_unverified"}
    )
    assert "could not be reserved" in full
    assert "will not guess" in unknown


def test_exact_time_failures_are_fixed_database_categories():
    assert "exact time is not free" in build_exact_availability_failure_text(
        "en", "Dr. X is NOT free between 7:00 PM and 7:15 PM."
    )
    assert "not confirmed yet" in build_exact_availability_failure_text(
        "en", "SCHEDULE NOT PUBLISHED"
    )
    assert "will not guess" in build_exact_availability_failure_text(
        "en", "unexpected provider response"
    )


def test_live_mutation_failure_stops_before_gemini(monkeypatch):
    session = _RecordingSession()
    agent = _agent()
    monkeypatch.setattr(agent_module, "AgentSession", _RecordingSession)
    context = SimpleNamespace(session=session)

    with pytest.raises(StopResponse):
        agent._stop_on_mutation_failure(
            context,
            "cancel",
            {"success": False, "error": "cancellation_outcome_unverified"},
        )

    assert len(session.spoken) == 1
    assert "will not guess" in session.spoken[0][0]


def test_every_critical_mutation_tool_has_a_rule_based_failure_exit():
    import inspect

    for method_name in (
        "assign_token",
        "confirm_booking",
        "reschedule_booking",
        "cancel_booking",
    ):
        source = inspect.getsource(getattr(VachanamAgent, method_name))
        assert "_stop_on_mutation_failure" in source, method_name
