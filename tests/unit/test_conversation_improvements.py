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
    assert "Fragments and trailing-off thoughts are not turns" in p
    assert "do NOT repeat\nyour full question" in p


def test_prompt_teaches_language_gap_recovery():
    """Transcript 16:48Z: Hindi speaker on an en-mapped call got the same
    English question re-asked into the gap for 75s. After an unintelligible
    streak the agent must offer a language switch once."""
    p = _prompt()
    assert "2–3 unintelligible turns" in p
    assert "switch_language" in p


def test_reminder_extra_gates_cancel_claims_on_tool_success():
    """Transcript 10:31Z: agent said 'already cancelled' — DB shows that token
    ended no_show, never cancelled. Cancel claims need tool success=true."""
    t = REMINDER_PROMPT_EXTRA
    assert "private_context" in t
    assert "MUST NEVER be spoken" in t
    assert "only after the action succeeded" in t
    assert "new_date" not in t and "calendar.tool" not in t


def test_receptionist_playbook_block_present():
    """2026-07-04 receptionist-role pass (docs/research/receptionist-rules-te.md
    R6/R8 + role research): booking close-with-what-next, messy openings
    (noise / silent caller / wrong number), and message-taking discipline."""
    p = _prompt()
    assert "<escalation>" in p
    # The offer exists, but the 2026-07-21 repetition fix makes it optional once.
    assert "Offer more help ONCE per call" in p
    assert "SILENT → one check" in p
    assert "NOISE or several voices" in p
    assert "WRONG NUMBER" in p
    assert "MESSAGE: confirm once, take_message" in p
    assert "log_clinic_question" in p
