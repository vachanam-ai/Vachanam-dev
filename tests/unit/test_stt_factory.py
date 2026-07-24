"""FIXLOG #300 — STT swap: Soniox stt-rt-v5 primary, Sarvam Saaras fallback.

Vinay 2026-07-10: Soniox is better + cheaper (~$0.12/hr real-time Telugu).
The contract that matters: the factory NEVER hard-requires the Soniox key —
an empty key falls back to Sarvam so the clinic can't go offline over a
missing/revoked secret (RULE 8), and the strict one-language-per-call rule
(Vinay 2026-06-17) survives the provider change.
"""
from unittest.mock import patch

from livekit.plugins import sarvam, soniox

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
    assert not hasattr(ag.settings, "soniox_api_key")


def test_sarvam_fallback_when_key_empty():
    """RULE 8: no Soniox key ⇒ Sarvam, never a crash / never no-STT."""
    with patch.object(ag.settings, "soniox_jp_api_key", ""):
        stt = ag._build_stt(get_lang("te"))
    assert isinstance(stt, sarvam.STT)


def test_language_switch_handoff_gets_new_language_hint():
    """switch_language handoff builds STT via the same factory — the NEW
    language must ride in the hints, not the old one."""
    with patch.object(ag.settings, "soniox_jp_api_key", "sk-test"):
        stt = ag._build_stt(get_lang("hi"))
    assert stt._params.language_hints == ["hi"]


def test_soniox_conservative_latency_profile_is_effective():
    with patch.multiple(
        ag.settings,
        soniox_jp_api_key="sk-test",
        stt_provider="auto",
        soniox_endpoint_latency_level=1,
        soniox_max_endpoint_delay_ms=2000,
        soniox_endpoint_sensitivity=None,
    ):
        stt = ag._build_stt(get_lang("te"))
    assert stt._params.endpoint_latency_adjustment_level == 1
    assert stt._params.max_endpoint_delay_ms == 2000
    assert stt._params.endpoint_sensitivity is None


def test_sarvam_can_be_forced_without_removing_soniox_key():
    with patch.multiple(
        ag.settings,
        soniox_jp_api_key="sk-test",
        stt_provider="sarvam",
    ):
        stt = ag._build_stt(get_lang("te"))
    assert isinstance(stt, sarvam.STT)


def test_delayed_finalize_wrapper_is_opt_in():
    controller = ag._SonioxFinalizeController(delay_ms=200)
    with patch.multiple(
        ag.settings,
        soniox_jp_api_key="sk-test",
        stt_provider="soniox",
    ):
        stt = ag._build_stt(
            get_lang("te"),
            finalize_controller=controller,
        )
    assert isinstance(stt, ag._FinalizingSonioxSTT)
    assert stt._finalize_controller is controller


def test_no_direct_sarvam_construction_outside_factory():
    """All three former sarvam.STT( sites must route through _build_stt, or a
    future edit could silently pin one path to the wrong provider."""
    import inspect

    src = inspect.getsource(ag)
    # the only sarvam.STT( left is inside _build_stt itself
    assert src.count("sarvam.STT(") == 1
    # Construction is selected dynamically so the same factory can attach the
    # session-scoped delayed-finalize controller without another provider site.
    assert "else soniox.STT" in src
