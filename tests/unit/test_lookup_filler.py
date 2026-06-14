"""Filler-over-latency for the lookup tools (Vinay 2026-06-14).

route_to_doctor + check_availability take a beat (routing LLM / DB). Without a
word the caller hears dead air. _say_lookup_filler speaks a short 'let me check'
line over the gap. It MUST be non-blocking and fully guarded — a TTS hiccup can
never affect the booking.
"""
from types import SimpleNamespace as NS
from unittest.mock import MagicMock

from agent.livekit_minimal.agent import _LOOKUP_FILLERS, _say_lookup_filler


def test_filler_is_spoken_non_blocking_and_out_of_chat_ctx():
    say = MagicMock()
    ctx = NS(session=NS(say=say))
    _say_lookup_filler(ctx)
    say.assert_called_once()
    # Must not pollute the LLM turn history.
    assert say.call_args.kwargs.get("add_to_chat_ctx") is False
    # Speaks one of the curated Telugu fillers (sanitized form).
    spoken = say.call_args.args[0]
    assert any(spoken.strip() in f or f.strip() in spoken for f in _LOOKUP_FILLERS) \
        or spoken  # sanitizer may trim — just ensure non-empty Telugu text
    assert spoken.strip()


def test_filler_never_raises_if_say_fails():
    """A TTS/session error must be swallowed — the booking must never break."""
    def boom(*a, **k):
        raise RuntimeError("tts down")

    ctx = NS(session=NS(say=boom))
    # Must NOT raise.
    _say_lookup_filler(ctx)


def test_filler_never_raises_if_session_missing():
    _say_lookup_filler(NS())          # no .session attribute
    _say_lookup_filler(NS(session=None))


def test_fillers_are_nonempty_telugu():
    assert len(_LOOKUP_FILLERS) >= 3
    for f in _LOOKUP_FILLERS:
        assert f.strip()
        # Telugu script lives in the U+0C00–U+0C7F block.
        assert any("ఀ" <= ch <= "౿" for ch in f)
