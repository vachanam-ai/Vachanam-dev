"""v21 prompt scaffold (2026-07-30): kill-switched rebuild of the production
voice prompt — concise, front-loaded grounding, positive-framed. See
docs/superpowers/specs/2026-07-30-voice-prompt-redesign-design.md §4.3/4.5.

The flag defaults OFF: production keeps the proven v20 prompt
(<poml>/<regressions>) until v21 is validated on real calls.
"""
import pytest

from agent.prompts.system_prompt import build_system_prompt, DoctorContext


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


# --------------------------------------------------------------------------
# Task 1.3 — _build_v21 scaffold: structure + preservation
# --------------------------------------------------------------------------


def _v21(monkeypatch, language="te"):
    from backend.config import settings
    monkeypatch.setattr(settings, "voice_prompt_v21", True)
    d = DoctorContext(id="1", name="Dr. Ravi", specialization="skin",
                      routing_keywords=["skin"], booking_type="appointment", is_default=True)
    return build_system_prompt(clinic_name="Sri Clinic", doctors=[d],
                               emergency_contact="+919999999999", plan="clinic", language=language)


def test_v21_grounding_is_front_loaded(monkeypatch):
    p = _v21(monkeypatch)
    assert p.index("<grounding>") < p.index("<scope>") < p.index("<flow>")
    assert p.index("<grounding>") < p.index("<edges>")


def test_v21_has_new_sections_and_drops_regressions(monkeypatch):
    p = _v21(monkeypatch)
    for tag in ("<grounding>", "<safety>", "<edges>", "<language>"):
        assert tag in p
    assert "<regressions>" not in p


def test_v21_is_substantially_shorter(monkeypatch):
    from backend.config import settings
    d = DoctorContext(id="1", name="Dr. Ravi", specialization="skin",
                      routing_keywords=["skin"], booking_type="appointment", is_default=True)
    monkeypatch.setattr(settings, "voice_prompt_v21", False)
    v20 = build_system_prompt(clinic_name="Sri Clinic", doctors=[d], emergency_contact="x", plan="clinic", language="te")
    monkeypatch.setattr(settings, "voice_prompt_v21", True)
    v21 = build_system_prompt(clinic_name="Sri Clinic", doctors=[d], emergency_contact="x", plan="clinic", language="te")
    assert len(v21) < 0.70 * len(v20)          # >=30% shorter


def test_v21_fewer_hard_negations(monkeypatch):
    from backend.config import settings
    d = DoctorContext(id="1", name="Dr. Ravi", specialization="skin",
                      routing_keywords=["skin"], booking_type="appointment", is_default=True)
    monkeypatch.setattr(settings, "voice_prompt_v21", False)
    v20 = build_system_prompt(clinic_name="C", doctors=[d], emergency_contact="x", plan="clinic", language="te")
    monkeypatch.setattr(settings, "voice_prompt_v21", True)
    v21 = build_system_prompt(clinic_name="C", doctors=[d], emergency_contact="x", plan="clinic", language="te")
    assert v21.count("NEVER") < 0.5 * v20.count("NEVER")


def test_v21_preserves_expressions_and_listed_name_rule(monkeypatch):
    p = _v21(monkeypatch)
    assert "[softly]" in p and "[happily]" in p     # expression tags kept
    assert "listed name or ID" in p                 # #294 doctor-match rule kept


@pytest.mark.parametrize("lang", ["te", "hi", "en"])
def test_v21_renders_all_configured_languages(monkeypatch, lang):
    assert len(_v21(monkeypatch, lang)) > 500


def test_v21_switch_section_minimal_no_full_native_dump(monkeypatch):
    # Telugu call must not embed every other language's native switch line.
    p = _v21(monkeypatch, "te")
    # Devanagari (Hindi) native switch_affirm must NOT appear in a Telugu render.
    assert "हाँ जी, हिंदी में बात कर सकती हूँ." not in p
