"""Task 2 (2026-07-30 voice-prompt-redesign) — Phase 2 structural grounding
gate. `voice_grounding_gate` defaults OFF: with it off, `_handle_grounded_user_turn`
and `tts_node` behave EXACTLY as before this change.
"""


def test_grounding_gate_flag_defaults_off():
    from backend.config import settings

    assert settings.voice_grounding_gate is False
