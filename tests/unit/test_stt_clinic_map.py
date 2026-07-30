"""Phase 3 (2026-07-30 voice-prompt-redesign) — phonetic STT → clinic-term map.

`nearest_clinic_term` snaps a Soniox mishear onto the real clinic vocabulary
using the same phonetic_fold + difflib technique as booking identity matching.
Conservative: exact fold match any length; fuzzy only for tokens >= 4 chars.
The `voice_stt_clinic_map` kill-switch defaults OFF.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace
from uuid import UUID

from agent.i18n.transliterate import nearest_clinic_term
from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState

VOCAB = ["Lakshmi", "Srinivas", "skin", "dental"]

BRANCH_ID = UUID("2e6d5a8a-30f0-4a90-9a9c-000000000003")


def _agent(vocab):
    return VachanamAgent(
        instructions="unused",
        state=SessionState(branch_id=BRANCH_ID, branch_timezone="Asia/Kolkata", language="en"),
        db=object(), room=None, calendar_service=None, meta_service=None,
        transfer_to="", lang_code="en", clinic_vocab=vocab,
    )


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


# ── Task 3.3: pre-routing application ────────────────────────────────────────


def test_apply_clinic_map_remaps_close_token():
    agent = _agent(["Lakshmi", "Srinivas"])
    msg = SimpleNamespace(text_content="book with lakshmee tomorrow", content=None)
    agent._apply_clinic_map(msg)
    assert msg.text_content == "book with Lakshmi tomorrow"


def test_apply_clinic_map_preserves_punctuation():
    agent = _agent(["Lakshmi"])
    msg = SimpleNamespace(text_content="lakshmee?", content=None)
    agent._apply_clinic_map(msg)
    assert msg.text_content == "Lakshmi?"


def test_apply_clinic_map_leaves_distinct_tokens_untouched():
    agent = _agent(["Lakshmi"])
    msg = SimpleNamespace(text_content="I need an appointment", content=None)
    agent._apply_clinic_map(msg)
    assert msg.text_content == "I need an appointment"


def test_apply_clinic_map_updates_content_when_string():
    agent = _agent(["Srinivas"])
    msg = SimpleNamespace(text_content=None, content="see shreenivas please")
    agent._apply_clinic_map(msg)
    assert msg.content == "see Srinivas please"


def test_apply_clinic_map_indic_script_token_untouched():
    # phonetic_fold is Latin-only: an Indic-script token folds to empty and is
    # never remapped (cross-script resolution stays with Soniox biasing).
    agent = _agent(["Lakshmi"])
    msg = SimpleNamespace(text_content="డాక్టర్ లక్ష్మి", content=None)
    agent._apply_clinic_map(msg)
    assert msg.text_content == "డాక్టర్ లక్ష్మి"


def test_pre_routing_application_is_flag_gated():
    """The remap must run only under settings.voice_stt_clinic_map (default
    off), so a transcript reaches routing byte-identical to today when off."""
    src = inspect.getsource(VachanamAgent.on_user_turn_completed)
    assert "settings.voice_stt_clinic_map" in src
    assert "_apply_clinic_map" in src
