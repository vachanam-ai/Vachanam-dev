"""Single-intro language switch + date speak-check (Vinay 2026-07-03, third
live round; transcript 17:49Z showed THREE utterances on switch and the agent
insisting 'this Wednesday is July ninth' when the table said July 8).

Mechanical guarantee for the single intro: livekit only generates a post-tool
reply when the tool returned an output (generation.make_tool_output:
`reply_required = fnc_out is not None`) — so switch_language must return the
Agent ALONE, and the on_enter ack is the only speech.
"""
import inspect
from datetime import datetime
from zoneinfo import ZoneInfo

from agent.i18n import LANGUAGES
from agent.i18n.lines import SWITCH_ACK
from agent.livekit_minimal.agent import VachanamAgent
from agent.prompts.system_prompt import build_date_context, build_system_prompt


def test_switch_tool_returns_agent_alone_and_interrupts_old_speech():
    src = inspect.getsource(VachanamAgent.__dict__["switch_language"])
    # Bare-Agent return => reply_required=False => no post-handoff LLM reply.
    assert "return new_agent\n" in src or src.rstrip().endswith("return new_agent")
    assert "return new_agent, {" not in src
    # Old voice's in-flight sentence is cut at the switch.
    assert "interrupt()" in src


def test_switch_ack_is_the_specified_intro():
    """Vinay: the switched voice says ONLY 'I can speak X. How can I help you?'"""
    assert SWITCH_ACK["en"] == "I can speak English. How can I help you?"
    for code in LANGUAGES:
        assert SWITCH_ACK[code].strip()


def test_switch_turn_says_at_most_ok():
    p = build_system_prompt(
        clinic_name="T", doctors=[], emergency_contact="9",
        plan="clinic", language="te",
    )
    assert 'old language or a bare "Ok" is a failure' in p


def test_date_context_speak_check_and_correct_wednesday():
    """2026-07-03 (Friday): the table must map Wednesday -> 2026-07-08, and the
    prompt must forbid arguing with a caller's date correction."""
    now = datetime(2026, 7, 3, 12, 0, tzinfo=ZoneInfo("Asia/Kolkata"))
    ctx = build_date_context(now)
    assert "Wednesday = 2026-07-08" in ctx
    assert "2026-07-09" in ctx  # Thursday row exists...
    assert "Wednesday = 2026-07-09" not in ctx  # ...but never as Wednesday
    assert "SPEAK-CHECK" in ctx
    assert "NEVER argue" in ctx


def test_prompt_has_failure_recovery_and_fragment_tool_gate():
    """τ-Voice/Full-Duplex-Bench findings: agents go unresponsive after repeated
    tool failures and fire tools on disfluent fragments."""
    p = build_system_prompt(
        clinic_name="T", doctors=[], emergency_contact="9",
        plan="clinic", language="te",
    )
    assert "A TOOL THAT FAILS, TIMES OUT, OR RETURNS NOTHING GIVES YOU NO FACT" in p
    assert "NO TOOLS ON FRAGMENTS" in p
    assert "Interrupted confirmation → restate only the unheard detail" in p
