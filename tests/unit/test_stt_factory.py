"""FIXLOG #300 — STT: Soniox stt-rt-v5, the SOLE provider (Sarvam removed
2026-07-30).

Vinay 2026-07-10: Soniox is better + cheaper (~$0.12/hr real-time Telugu). There
is no fallback provider anymore — a missing SONIOX_JP_API_KEY raises loudly at
call setup rather than silently degrading to a dead line. The strict
one-language-per-call rule (Vinay 2026-06-17) survives.
"""
from unittest.mock import patch

import pytest
from livekit.plugins import soniox

import agent.livekit_minimal.agent as ag
from agent.i18n.languages import get_lang


def test_soniox_when_key_set():
    with patch.object(ag.settings, "soniox_jp_api_key", "sk-test"):
        stt = ag._build_stt(get_lang("te"))
    assert isinstance(stt, soniox.STT)
    opts = stt._params
    assert opts.model == "stt-rt-v5"
    # strict ONE language per call — hints pinned to the branch language
    assert opts.language_hints == ["te"]
    assert opts.language_hints_strict is True
    assert stt._base_url == "wss://stt-rt.jp.soniox.com/transcribe-websocket"


def test_missing_key_raises_no_fallback():
    """No Soniox key ⇒ hard RuntimeError. Sarvam fallback is gone: loud failure
    at call setup beats a silent dead line."""
    with patch.object(ag.settings, "soniox_jp_api_key", ""):
        with pytest.raises(RuntimeError, match="SONIOX_JP_API_KEY"):
            ag._build_stt(get_lang("te"))


def test_language_switch_handoff_gets_new_language_hint():
    """switch_language handoff builds STT via the same factory — the NEW
    language must ride in the hints, not the old one."""
    with patch.object(ag.settings, "soniox_jp_api_key", "sk-test"):
        stt = ag._build_stt(get_lang("hi"))
    assert stt._params.language_hints == ["hi"]


def test_soniox_documented_low_latency_profile_is_effective():
    with patch.multiple(
        ag.settings,
        soniox_jp_api_key="sk-test",
        soniox_endpoint_latency_level=2,
        soniox_max_endpoint_delay_ms=1500,
        soniox_endpoint_sensitivity=0.3,
    ):
        stt = ag._build_stt(get_lang("te"))
    assert stt._params.endpoint_latency_adjustment_level == 2
    assert stt._params.max_endpoint_delay_ms == 1500
    assert stt._params.endpoint_sensitivity == 0.3


def test_delayed_finalize_wrapper_is_opt_in():
    controller = ag._SonioxFinalizeController(delay_ms=200)
    with patch.object(ag.settings, "soniox_jp_api_key", "sk-test"):
        stt = ag._build_stt(get_lang("te"), finalize_controller=controller)
    assert isinstance(stt, ag._FinalizingSonioxSTT)
    assert stt._finalize_controller is controller


def test_no_sarvam_stt_construction_or_import():
    """Sarvam is removed from the STT path: no plugin import, no construction.
    (Historical latency COMMENTS may still name Sarvam — this guards code.)"""
    import inspect

    src = inspect.getsource(ag)
    assert "sarvam.STT(" not in src
    assert "import sarvam" not in src
    assert "noise_cancellation, sarvam" not in src  # old plugins import line
