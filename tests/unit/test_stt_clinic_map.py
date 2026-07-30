"""Phase 3 (2026-07-30 voice-prompt-redesign) — phonetic STT → clinic-term map.

`nearest_clinic_term` snaps a Soniox mishear onto the real clinic vocabulary
using the same phonetic_fold + difflib technique as booking identity matching.
Conservative: exact fold match any length; fuzzy only for tokens >= 4 chars.
The `voice_stt_clinic_map` kill-switch defaults OFF.
"""
from __future__ import annotations

from agent.i18n.transliterate import nearest_clinic_term

VOCAB = ["Lakshmi", "Srinivas", "skin", "dental"]


def test_maps_close_mishear():
    assert nearest_clinic_term("lakshmee", VOCAB) == "Lakshmi"


def test_no_map_for_distinct_word():
    assert nearest_clinic_term("appointment", VOCAB) is None


def test_exact_passes_through():
    assert nearest_clinic_term("skin", VOCAB) == "skin"


def test_empty_token_or_vocab_is_none():
    assert nearest_clinic_term("", VOCAB) is None
    assert nearest_clinic_term("lakshmee", []) is None


def test_short_token_never_fuzzy_maps():
    # A 3-char token must not be dragged onto a longer clinic name even if it
    # shares a prefix — only an exact fold would map it.
    assert nearest_clinic_term("lak", VOCAB) is None


def test_threshold_is_respected():
    # A weak resemblance below threshold does not map.
    assert nearest_clinic_term("dennis", VOCAB) is None


def test_flag_defaults_off():
    from backend.config import settings

    assert settings.voice_stt_clinic_map is False
