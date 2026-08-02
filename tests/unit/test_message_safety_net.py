"""Message safety net (Vinay real call 2026-07-17: agent said "డాక్టర్ గారికి
తెలియజేస్తాను" without calling take_message — the message silently vanished).
Belt: prompt forbids the promise before the tool. Suspenders: teardown
auto-captures the caller's words when a spoken promise has no recorded row."""
from pathlib import Path

from agent.session_state import SessionState

AGENT_SRC = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
PROMPT_SRC = Path("agent/prompts/grounded_prompt.py").read_text(encoding="utf-8")


def test_state_carries_recording_flags():
    s = SessionState(session_id="t", branch_id=None)
    assert s.message_taken is False and s.question_logged is False


def test_tools_set_flags_on_success():
    # take_message success path flips message_taken; log_clinic_question flips
    # question_logged — the net keys off these.
    assert "self._state.message_taken = True" in AGENT_SRC
    assert "self._state.question_logged = True" in AGENT_SRC


def test_teardown_net_present_and_guarded():
    net = AGENT_SRC.split("MESSAGE SAFETY NET")[1][:5000]
    # fires only when NOTHING was recorded, never for sales, never breaks teardown
    assert "not state.message_taken" in net
    assert "not state.question_logged" in net
    assert "not state.token_confirmed" in net
    assert "auto-captured" in net
    # the exact phrase the failed call used is a marker
    assert "తెలియజేస్తాను" in net


def test_ask_the_doctor_promise_is_caught_as_a_question():
    """2026-08-02 real call ("do you have a plastic surgeon?"): the agent used
    the ask-the-doctor line, which matched NO marker, so nothing was captured.
    Every language's ask_doctor line is now a marker, and an ask-shaped promise
    lands as a ClinicQuestion (answerable + auto callback), not a message."""
    from agent.prompts.grounded_prompt import PACKS

    net = AGENT_SRC.split("MESSAGE SAFETY NET")[1][:8000]
    for code, pack in PACKS.items():
        ask = (pack.ask_doctor or "").replace("[hesitates]", "").strip()
        if not ask:
            continue
        assert any(marker in ask for marker in _markers(net)), (
            f"{code} ask_doctor line has no safety-net marker: {ask}"
        )
    assert "_CQ(" in net  # ask-shaped promise → clinic question row


def _markers(net: str) -> list[str]:
    block = net.split("_ASK_PROMISES = (")[1].split(")")[0]
    return [chunk.split('"')[1] for chunk in block.split(",") if '"' in chunk]


def test_prompt_forbids_promise_before_tool():
    # v19 dropped the "SAYING IS NOT DOING" label; the rule now reads
    # "Never send or promise ... from speech" + "claim delivery only after success".
    assert "Never send or promise" in PROMPT_SRC and "from speech" in PROMPT_SRC
    assert "take_message" in PROMPT_SRC
    assert "claim delivery only after success" in PROMPT_SRC


def test_wrong_name_recovery_natural_398():
    """#398 (real call 2026-07-18: greeted 'Hitesh gaaru?', caller said no,
    agent asked 'first time maatladutunnara?' — interrogation). The known-
    caller extra must carry the human recovery branch + the forbidden quiz."""
    assert "IF THE CALLER SAYS THAT NAME IS WRONG" in AGENT_SRC
    assert "అయ్యో సారీ అండి" in AGENT_SRC
    assert "ఫస్ట్ టైమ్ మాట్లాడుతున్నారా" in AGENT_SRC  # named as FORBIDDEN
