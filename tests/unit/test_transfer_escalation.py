"""#350 (Vinay, real-call evidence 2026-07-12 17:36 IST): transfer escalation
contract — urgent situations connect IMMEDIATELY; a non-urgent doctor-ask gets
at most TWO deflections (help, then message) and the THIRD ask always
transfers; a failed transfer hands the caller the emergency number aloud
instead of a dead end."""
import uuid

import pytest

from agent.i18n.lines import TRANSFER_NOTICE, get_transfer_notice
from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.system_prompt import build_system_prompt
from agent.session_state import SessionState


def _prompt():
    return build_system_prompt(
        clinic_name="C", doctors=[], emergency_contact="+911234567890",
        plan="clinic", language="te", faq=None,
    )


def test_prompt_urgent_transfers_immediately():
    p = " ".join(_prompt().split())
    assert "URGENT NOW" in p
    assert 'request_human_transfer(reason="urgent") silently and immediately' in p
    # RULE 7: intent-based, never keyword triage.
    assert "never a keyword list" in p


def test_prompt_third_ask_always_transfers():
    p = " ".join(_prompt().split())
    assert "offer receptionist help at most TWICE" in p
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


def test_every_call_language_has_urgent_and_routine_transfer_notices():
    assert set(TRANSFER_NOTICE) == {"te", "en", "hi", "ta", "kn", "ml", "mr", "bn"}
    for code in TRANSFER_NOTICE:
        urgent = get_transfer_notice(code, urgent=True)
        routine = get_transfer_notice(code, urgent=False)
        assert urgent and routine and urgent != routine
        assert "{" not in urgent + routine


@pytest.mark.asyncio
async def test_urgent_notice_finishes_before_sip_transfer(monkeypatch, caplog):
    events = []

    class _Speech:
        async def wait_for_playout(self):
            events.append("playout")

    class _Session:
        userdata = {}

        async def say(self, text, **kwargs):
            events.append(("say", text, kwargs))
            return _Speech()

    class _Room:
        name = "urgent-room"
        remote_participants = {"sip_patient": object()}

    class _SIP:
        async def transfer_sip_participant(self, request):
            events.append("transfer")

    class _LiveKit:
        sip = _SIP()

        async def aclose(self):
            return None

    class _Agent(VachanamAgent):
        @property
        def session(self):
            return self._test_session

    agent = _Agent(
        instructions="x",
        state=SessionState(branch_id=uuid.uuid4()),
        db=None,
        room=_Room(),
        calendar_service=None,
        meta_service=None,
        transfer_to="+911234567890",
        lang_code="te",
    )
    agent._test_session = _Session()
    monkeypatch.setattr(
        "agent.livekit_minimal.agent.api.LiveKitAPI", lambda: _LiveKit()
    )
    sensitive_reason = "urgent PRIVACY_TRANSFER_SENTINEL chest symptoms"
    caplog.set_level("INFO", logger="vachanam-agent")

    out = await agent.request_human_transfer(None, reason=sensitive_reason)

    assert out["success"] is True
    assert "human_transfer_requested" in caplog.text
    assert sensitive_reason not in caplog.text
    assert events[0][0] == "say"
    assert events[0][1] == get_transfer_notice("te", urgent=True)
    assert events[0][2]["allow_interruptions"] is False
    assert events[1:] == ["playout", "transfer"]
