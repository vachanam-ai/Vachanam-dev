"""Guard: the live system prompt must explicitly forbid Latin AM/PM + clock
times in spoken output (RULE 6 — TTS spells Latin letter-by-letter). Found via
the humanizer multi-turn sim (agent said "9:30 AM")."""
from agent.prompts.system_prompt import build_system_prompt


def test_prompt_bans_latin_am_pm_and_clock_times():
    p = build_system_prompt("ఆరోగ్య", [], "", "clinic", language="te")
    assert '"AM"' in p and '"PM"' in p
    assert "TTS spells Latin" in p
    # the corrective Telugu day-part form is shown as the required style
    assert "ఉదయం తొమ్మిదిన్నరకి" in p
