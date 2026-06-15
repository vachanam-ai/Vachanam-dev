"""Filler-over-latency for the lookup tools (Vinay 2026-06-14).

route_to_doctor + check_availability take a beat (routing LLM / DB). Without a
word the caller hears dead air. _say_lookup_filler speaks a short 'let me check'
line over the gap. It MUST be non-blocking and fully guarded — a TTS hiccup can
never affect the booking. The clinic-language fillers ride on the session
userdata (2026-06-15 multilingual); Telugu is the fallback.
"""
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from agent.i18n import get_lines
from agent.livekit_minimal.agent import _FALLBACK_FILLERS, _say_lookup_filler


def test_filler_is_spoken_non_blocking_and_out_of_chat_ctx():
    say = MagicMock()
    ctx = NS(session=NS(say=say, userdata=None))
    _say_lookup_filler(ctx)
    say.assert_called_once()
    # Must not pollute the LLM turn history.
    assert say.call_args.kwargs.get("add_to_chat_ctx") is False
    # Falls back to a curated Telugu filler when no userdata is set.
    spoken = say.call_args.args[0]
    assert spoken.strip()


def test_filler_uses_session_language_fillers():
    """When the session carries the clinic's language fillers, speak those."""
    say = MagicMock()
    hi_fillers = get_lines("hi").fillers
    ctx = NS(session=NS(say=say, userdata={"fillers": hi_fillers, "language": "hi"}))
    _say_lookup_filler(ctx)
    spoken = say.call_args.args[0]
    # The spoken line came from the Hindi set, not the Telugu fallback.
    assert any(spoken.strip() in f or f.strip() in spoken for f in hi_fillers)


def test_filler_never_raises_if_say_fails():
    """A TTS/session error must be swallowed — the booking must never break."""
    def boom(*a, **k):
        raise RuntimeError("tts down")

    ctx = NS(session=NS(say=boom, userdata=None))
    _say_lookup_filler(ctx)  # Must NOT raise.


def test_filler_never_raises_if_session_missing():
    _say_lookup_filler(NS())          # no .session attribute
    _say_lookup_filler(NS(session=None))


def test_fallback_fillers_are_nonempty_telugu():
    assert len(_FALLBACK_FILLERS) >= 3
    for f in _FALLBACK_FILLERS:
        assert f.strip()
        # Telugu script lives in the U+0C00–U+0C7F block.
        assert any("ఀ" <= ch <= "౿" for ch in f)
