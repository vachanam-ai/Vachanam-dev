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
    """SUPERSEDED 2026-08-09. This used to pin "I can speak English. How can I
    help you?" — Vinay's 07-03 instruction. His 08-09 one replaces it:

        "instead of saying 'yes, i can speak in <language>', make it as ok, and
        repeat previous response which you gave."

    A receptionist handed a new language answers the question in it; she does
    not announce that she speaks it and wait to be asked again. So the ack is
    now a single word and the restatement follows it."""
    assert SWITCH_ACK["en"] == "Sure."
    for code in LANGUAGES:
        line = SWITCH_ACK[code]
        assert line.strip()
        assert len(line.split()) <= 3, (
            f"{code} ack is a sentence, not an acknowledgement: {line!r}"
        )


def test_no_ack_claims_the_ability_to_speak():
    """The exact phrasing Vinay asked to be removed, in every language it was
    written in."""
    for code, line in SWITCH_ACK.items():
        low = line.lower()
        for claim in ("i can speak", "మాట్లాడ", "बात कर", "பேச", "ಮಾತಾಡ", "বলতে"):
            assert claim not in low, f"{code} still announces the language: {line!r}"


def test_switch_turn_says_at_most_ok():
    """A bare "Ok" is STILL a failure — but now because the answer never
    followed it, not because the proof sentence was missing."""
    p = build_system_prompt(
        clinic_name="T", doctors=[], emergency_contact="9",
        plan="clinic", language="te",
    )
    assert 'stopping at a bare "Ok"' in p
    assert "NEVER say you can speak the language" in p
    assert "PREVIOUS ANSWER again in the new" in p


def test_the_switched_agent_is_told_to_restate():
    """The deterministic half. The prompt covers the model calling
    switch_language itself; this covers _handoff_explicit_language, which
    switches the pipeline WITHOUT the model's involvement — two paths reach a
    language switch and both have to restate, or the fix works only sometimes."""
    from agent.livekit_minimal.agent import _SWITCH_RESTATE, VachanamAgent

    on_enter = inspect.getsource(VachanamAgent.on_enter)
    assert "_SWITCH_RESTATE" in on_enter, "the ack plays and nothing follows it"
    assert on_enter.index("switch_ack_failed") < on_enter.index("_SWITCH_RESTATE"), (
        "restatement must come after the ack, not before it"
    )
    low = _SWITCH_RESTATE.lower()
    assert "previous answer" in low
    assert "do not greet" in low
    assert "ask how you can help" in low, "no fallback for a switch before any answer"


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
    assert "A TOOL THAT FAILS, TIMES OUT OR RETURNS NOTHING GIVES YOU NO FACT" in p
    assert "NO TOOLS ON FRAGMENTS" in p
    assert "Interrupted confirmation → restate only the unheard detail" in p
