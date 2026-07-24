"""#350 (Vinay, real-call evidence 2026-07-12 17:36 IST): transfer escalation
contract — urgent situations connect IMMEDIATELY; a non-urgent doctor-ask gets
at most TWO deflections (help, then message) and the THIRD ask always
transfers; a failed transfer hands the caller the emergency number aloud
instead of a dead end."""
import uuid

import pytest

from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.system_prompt import build_system_prompt
from agent.session_state import SessionState


def _prompt():
    return build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te", faq=None,
    )


def test_prompt_urgent_transfers_immediately():
    p = _prompt()
    assert "URGENT NOW" in p
    assert 'request_human_transfer(reason="urgent") immediately' in p
    # RULE 7: intent-based, never keyword triage.
    assert "never a keyword list" in p


def test_prompt_third_ask_always_transfers():
    p = _prompt()
    assert "offer help at most TWICE" in p
    assert "3rd ask" in p
    assert "3rd ask transfers" in p


def test_prompt_booking_rule_defers_to_urgent():
    p = _prompt()
    assert "new appointment → BOOKING (unless URGENT NOW)" in p


def _agent(transfer_to, room=None):
    return VachanamAgent(
        instructions="x",
        state=SessionState(branch_id=uuid.uuid4()),
        db=None,
        room=room,
        calendar_service=None,
        meta_service=None,
        transfer_to=transfer_to,
        lang_code="te",
    )


@pytest.mark.asyncio
async def test_transfer_unavailable_still_gives_a_path():
    a = _agent(transfer_to="")
    out = await a.request_human_transfer(None, reason="urgent: chest pain")
    assert out["success"] is False and out["error"] == "transfer_unavailable"
    assert "take_message" in out["next"]  # never a dead end


@pytest.mark.asyncio
async def test_transfer_failed_returns_emergency_number():
    class _Room:
        name = "r"
        remote_participants = {"sip_1": object()}

    a = _agent(transfer_to="+911234567890", room=_Room())
    # api.LiveKitAPI() will fail fast in tests (no LIVEKIT env server) —
    # exactly the transfer_failed path we want; if it somehow succeeds the
    # assertion below catches it.
    out = await a.request_human_transfer(None, reason="persistent: doctor")
    assert out["success"] is False
    assert out["error"] in ("transfer_failed", "no_participant")
    if out["error"] == "transfer_failed":
        assert out["emergency_contact"] == "+911234567890"
        assert "digit by digit" in out["next"]
