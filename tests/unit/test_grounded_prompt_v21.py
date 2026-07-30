"""v21 prompt scaffold (2026-07-30): kill-switched rebuild of the production
voice prompt — concise, front-loaded grounding, positive-framed. See
docs/superpowers/specs/2026-07-30-voice-prompt-redesign-design.md §4.3/4.5.

The flag defaults OFF: production keeps the proven v20 prompt
(<poml>/<regressions>) until v21 is validated on real calls.
"""


def test_prompt_v21_flag_defaults_off():
    from backend.config import settings
    assert settings.voice_prompt_v21 is False
