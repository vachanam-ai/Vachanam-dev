"""v21 prompt scaffold (2026-07-30): kill-switched rebuild of the production
voice prompt — concise, front-loaded grounding, positive-framed. See
docs/superpowers/specs/2026-07-30-voice-prompt-redesign-design.md §4.3/4.5.

The flag defaults OFF: production keeps the proven v20 prompt
(<poml>/<regressions>) until v21 is validated on real calls.
"""


def test_prompt_v21_flag_defaults_off():
    from backend.config import settings
    assert settings.voice_prompt_v21 is False


def test_flag_off_renders_v20_with_regressions_block():
    """Pins v20 as the untouched default so the v20/v21 split can't drift it."""
    from agent.prompts.system_prompt import build_system_prompt, DoctorContext
    d = DoctorContext(id="1", name="Dr. Ravi", specialization="skin",
                      routing_keywords=["skin"], booking_type="appointment", is_default=True)
    p = build_system_prompt(clinic_name="C", doctors=[d], emergency_contact="x",
                            plan="clinic", language="te")
    assert "<regressions>" in p            # v20 marker
    assert "<poml" in p
