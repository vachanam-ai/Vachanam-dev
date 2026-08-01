"""A caller must NEVER hear the word "database" (Vinay live 2026-07-31:
"unable to connect to DB … ragebaiting"). Two guards: the deterministic
fallback lines don't say it, and the TTS boundary scrubs it if the LLM parrots
a tool-result instruction or hallucinates one.
"""
from agent.livekit_minimal.workflow_rules import (
    build_exact_availability_failure_text,
    build_mutation_failure_text,
)
from agent.services.tts_sanitizer import sanitize_for_tts

_BANNED = ("database", "डेटाबेस", "డేటాబేస్")


def _clean(text: str) -> bool:
    low = text.lower()
    return "database" not in low and "डेटाबेस" not in text and "డేటాబేస్" not in text


def test_tts_boundary_scrubs_database_in_every_script():
    for leak in (
        "Sorry, I could not confirm that in the database. Shall I check again?",
        "the database did not verify success",
        "ఆ టైమ్‌ని డేటాబేస్‌లో నిర్ధారించలేకపోయాను. మళ్లీ చెక్ చేయనా?",
        "डेटाबेस में स्थिति सत्यापित नहीं हुई।",
    ):
        assert _clean(sanitize_for_tts(leak)), leak


def test_scrub_does_not_touch_normal_speech():
    ok = "One moment, let me connect you to the clinic."
    assert sanitize_for_tts(ok) == "One moment, let me connect you to the clinic."


def test_mutation_failure_lines_never_say_database():
    for lang in ("en", "te", "hi"):
        for op in ("book", "reschedule", "cancel", "reserve"):
            msg = build_mutation_failure_text(
                lang, op, {"success": False, "error": "outcome_unverified"}
            )
            assert _clean(msg), (lang, op, msg)


def test_availability_unverified_line_never_says_database():
    for lang in ("en", "te", "hi"):
        msg = build_exact_availability_failure_text(lang, "unexpected provider response")
        assert _clean(msg), (lang, msg)
