"""Odia removed (Vinay 2026-07-24). Platform drops to 7 Indian languages
(te/hi/ta/kn/ml/mr/bn) + English-on-request. Legacy Branch.language="or" rows
fall back to Telugu via get_lang, so no data migration is needed (RULE 8)."""
from __future__ import annotations

from pathlib import Path

from agent.i18n.languages import LANGUAGES, get_lang


def test_odia_gone_from_registry():
    assert "or" not in LANGUAGES
    assert set(LANGUAGES) == {"te", "en", "hi", "ta", "kn", "ml", "mr", "bn"}
    assert get_lang("or").code == "te"  # legacy rows fall back safely


def test_no_odia_left_in_i18n_sources():
    for f in (
        "agent/i18n/languages.py",
        "agent/i18n/lines.py",
        "agent/i18n/backchannels.py",
        "agent/i18n/transliterate.py",
    ):
        src = Path(f).read_text(encoding="utf-8")
        assert '"or":' not in src, f
        assert "Odia" not in src and "od-IN" not in src, f
