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
    with patch.object(ag.settings, "soniox_api_key", "sk-test"):
        stt = ag._build_stt(get_lang("te"))
    assert isinstance(stt, soniox.STT)
    opts = stt._params
    assert opts.model == "stt-rt-v5"
    # strict ONE language per call — hints pinned to the branch language
    assert opts.language_hints == ["te"]
    assert opts.language_hints_strict is True


def test_sarvam_fallback_when_key_empty():
    """RULE 8: no Soniox key ⇒ Sarvam, never a crash / never no-STT."""
    with patch.object(ag.settings, "soniox_api_key", ""):
        stt = ag._build_stt(get_lang("te"))
    assert isinstance(stt, sarvam.STT)


def test_language_switch_handoff_gets_new_language_hint():
    """switch_language handoff builds STT via the same factory — the NEW
    language must ride in the hints, not the old one."""
    with patch.object(ag.settings, "soniox_api_key", "sk-test"):
        stt = ag._build_stt(get_lang("hi"))
    assert stt._params.language_hints == ["hi"]


def test_no_direct_sarvam_construction_outside_factory():
    """All three former sarvam.STT( sites must route through _build_stt, or a
    future edit could silently pin one path to the wrong provider."""
    import inspect

    src = inspect.getsource(ag)
    # the only sarvam.STT( left is inside _build_stt itself
    assert src.count("sarvam.STT(") == 1
    assert src.count("soniox.STT(") == 1
