"""Unit tests for the call-quality capture helpers (FIXLOG #141).

Pure functions — no DB, no LiveKit session. They turn a call's chat history into
(patient_turns, phone-masked transcript) for the monitoring + feedback-loop
record, and must NEVER raise (capture is best-effort at call teardown).
"""
from types import SimpleNamespace

from agent.livekit_minimal.agent import _extract_call_record, _mask_pii_for_transcript


def _hist(*items):
    """Fake AgentSession with a .history.items list of role/text_content objects."""
    objs = [SimpleNamespace(role=r, text_content=t, content=None) for r, t in items]
    return SimpleNamespace(history=SimpleNamespace(items=objs))


def test_mask_pii_masks_phone_digit_runs():
    assert _mask_pii_for_transcript("call 9666444428 now") == "call [number] now"
    assert _mask_pii_for_transcript("token 1234 and 56") == "token [number] and 56"  # <4 digits kept


def test_mask_pii_keeps_normal_words():
    s = "patient: నాకు dental problem"
    assert _mask_pii_for_transcript(s) == s


def test_extract_counts_patient_turns_and_tags_roles():
    sess = _hist(
        ("user", "నాకు dental problem"),
        ("assistant", "సరే అండి, ఏ టైమ్?"),
        ("user", "my number is 9666444428"),
    )
    turns, transcript = _extract_call_record(sess)
    assert turns == 2  # two user/patient turns
    assert "patient:" in transcript and "agent:" in transcript
    assert "[number]" in transcript  # phone masked
    assert "9666444428" not in transcript


def test_extract_skips_system_and_tool_items():
    sess = _hist(
        ("system", "you are an assistant"),
        ("user", "hi"),
        ("tool", "{json}"),
    )
    turns, transcript = _extract_call_record(sess)
    assert turns == 1
    assert "you are an assistant" not in transcript


def test_extract_empty_history_is_safe():
    assert _extract_call_record(SimpleNamespace(history=None)) == (0, None)
    assert _extract_call_record(SimpleNamespace()) == (0, None)
