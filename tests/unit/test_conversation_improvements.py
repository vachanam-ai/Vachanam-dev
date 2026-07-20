"""Conversation-quality improvements from the 2026-07-03 transcript analysis
(10 prod calls read + LLM-judge run: avg 3.2/5; top tags slow_or_repetitive,
language_issue, stt_mishear, abandoned_unnecessarily).

Grounding: judge summaries ("agent repeated questions", "unnecessarily ended
the call after a minor booking issue") + voice-agent turn-taking literature
(incomplete utterances are not turns; repair, don't restart).
"""
from agent.livekit_minimal.agent import REMINDER_PROMPT_EXTRA
from agent.prompts.system_prompt import build_system_prompt


def _prompt(lang="te"):
    return build_system_prompt(
        clinic_name="Test", doctors=[], emergency_contact="9",
        plan="clinic", language=lang,
    )


def test_prompt_teaches_fragment_patience():
    """Transcript 16:42Z: caller fragments ("तो मुझे।", "हम्म।") each triggered a
    full re-prompt — caller felt talked over. Fragments are not turns."""
    p = _prompt()
    assert "INCOMPLETE UTTERANCES" in p
    assert "do NOT repeat your full question" in p


def test_prompt_teaches_language_gap_recovery():
    """Transcript 16:48Z: Hindi speaker on an en-mapped call got the same
    English question re-asked into the gap for 75s. After an unintelligible
    streak the agent must offer a language switch once."""
    p = _prompt()
    assert "UNINTELLIGIBLE STREAK" in p
    assert "switch_language" in p


def test_reminder_extra_gates_cancel_claims_on_tool_success():
    """Transcript 10:31Z: agent said 'already cancelled' — DB shows that token
    ended no_show, never cancelled. Cancel claims need tool success=true."""
    t = REMINDER_PROMPT_EXTRA
    assert "cancel_booking" in t
    assert "success=true" in t
    assert "NEVER claim a cancellation" in t


def test_receptionist_playbook_block_present():
    """2026-07-04 receptionist-role pass (docs/research/receptionist-rules-te.md
    R6/R8 + role research): booking close-with-what-next, messy openings
    (noise / silent caller / wrong number), and message-taking discipline."""
    p = _prompt()
    assert "RECEPTIONIST PLAYBOOK" in p
    # Renamed + strengthened #427: the booking close now REQUIRES an
    # offer-of-more-help beat before end_call, not just a what-next line.
    assert "OFFER MORE HELP BEFORE CLOSING" in p
    assert "SILENT CALLER" in p
    assert "BACKGROUND NOISE" in p
    assert "WRONG NUMBER" in p
    assert "MESSAGE FOR THE DOCTOR/CLINIC" in p
    assert "log_clinic_question" in p
