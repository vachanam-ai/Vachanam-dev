"""FIXLOG #298 — live 2026-07-09: Neon hit its data-transfer quota, every
entrypoint DB query raised, the agent died before answering, and callers heard
endless ringing. RULE 8 says a caller must ALWAYS get a coherent next step.

_end_call_with_notice answers, speaks the default-language "service stopped,
please call the clinic directly" line on a raw track (no DB, no LLM, no
session), and hangs up. Every step is best-effort — it must never raise.
"""
import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import agent.livekit_minimal.agent as ag
from agent.i18n import get_lang, get_lines
from agent.i18n.languages import DEFAULT_LANG


def _ctx():
    return SimpleNamespace(room=SimpleNamespace(name="call-test-room"))


@pytest.mark.asyncio
async def test_notice_speaks_default_language_line_and_hangs_up():
    played = {}

    async def fake_synth(room, texts, voice, lang, t_answer=None):
        played.update(room=room, texts=texts, voice=voice, lang=lang)
        return True

    fake_api = AsyncMock()
    with patch.object(ag, "synth_and_play", fake_synth), \
         patch.object(ag.api, "LiveKitAPI", return_value=fake_api), \
         patch.object(ag.asyncio, "sleep", AsyncMock()):
        await ag._end_call_with_notice(_ctx(), "db_unavailable: quota", 1.0)

    # spoke the real notice line, in the default language, with its default voice
    assert played["texts"] == [get_lines(DEFAULT_LANG).service_blocked]
    assert played["lang"] == DEFAULT_LANG
    assert played["voice"] == get_lang(DEFAULT_LANG).default_voice
    # and hung the call up
    fake_api.room.delete_room.assert_awaited()
    fake_api.aclose.assert_awaited()


@pytest.mark.asyncio
async def test_notice_still_hangs_up_when_playback_fails():
    """TTS down too? The call must still be ended, not left ringing."""
    async def boom(*a, **k):
        raise RuntimeError("tts down")

    fake_api = AsyncMock()
    with patch.object(ag, "synth_and_play", boom), \
         patch.object(ag.api, "LiveKitAPI", return_value=fake_api), \
         patch.object(ag.asyncio, "sleep", AsyncMock()):
        await ag._end_call_with_notice(_ctx(), "db_unavailable", None)

    fake_api.room.delete_room.assert_awaited()


@pytest.mark.asyncio
async def test_notice_never_raises_even_if_hangup_fails():
    """Total failure still returns cleanly — the entrypoint must not crash."""
    async def boom(*a, **k):
        raise RuntimeError("tts down")

    def api_boom():
        raise RuntimeError("livekit api down")

    with patch.object(ag, "synth_and_play", boom), \
         patch.object(ag.api, "LiveKitAPI", api_boom), \
         patch.object(ag.asyncio, "sleep", AsyncMock()):
        await ag._end_call_with_notice(_ctx(), "db_unavailable", None)  # must not raise


def test_notice_helper_is_wired_into_entrypoint_db_guard():
    """The branch-resolve DB block must be guarded and route to the notice —
    not left to raise (which is what produced the dead ringing)."""
    import inspect

    src = inspect.getsource(ag)
    guard = src.find("RULE 8 (#298)")
    assert guard != -1, "DB-outage guard comment missing"
    # the except path calls the notice helper, and did_resolution_failed does too
    assert "await _end_call_with_notice(ctx, f\"db_unavailable:" in src
    assert 'await _end_call_with_notice(ctx, "did_resolution_failed"' in src
