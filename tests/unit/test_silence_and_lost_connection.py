"""Silence line-check + lost-connection handling (Vinay 2026-07-20):

1. If the caller says nothing for 10s straight, the agent speaks a line-check
   ("hello, are you there? line lo unnara?"), repeats every 10s, and ends the
   call at 30s.
2. If the caller repeats "hello" 3 times in a row (not a single hello), the
   agent concludes one-way audio, speaks a reconnect notice, and hangs up.
"""
import inspect

import pytest
from types import SimpleNamespace

from agent.i18n.backchannels import is_lone_hello
from agent.i18n.lines import (
    LINE_CHECK,
    RECONNECT,
    get_line_check,
    get_reconnect,
)
from agent.livekit_minimal.agent import (
    LOST_HELLO_COUNT,
    SILENCE_END_S,
    SILENCE_PROMPT_EVERY_S,
    VachanamAgent,
    _silence_action,
)
from agent.session_state import SessionState


# ── Feature 1: silence escalation timing (pure) ──────────────────────────────

def test_silence_action_prompts_then_ends():
    # Below the first threshold: nothing.
    assert _silence_action(0, 0) is None
    assert _silence_action(9.9, 0) is None
    # 10s, none sent yet -> first prompt.
    assert _silence_action(10, 0) == "prompt"
    # Between 10 and 20, one already sent -> wait.
    assert _silence_action(15, 1) is None
    # 20s, one sent -> second prompt.
    assert _silence_action(20, 1) == "prompt"
    # Between 20 and 30, two sent -> wait.
    assert _silence_action(25, 2) is None
    # 30s -> end (regardless of prompts).
    assert _silence_action(30, 2) == "end"
    assert _silence_action(45, 2) == "end"


def test_silence_action_never_prompts_past_the_end():
    # A prompt must never be due at or beyond the end threshold.
    max_prompts = int(SILENCE_END_S // SILENCE_PROMPT_EVERY_S) - 1
    assert _silence_action(SILENCE_END_S - 0.01, 0) == "prompt"
    # Even from a fresh count, the last prompt slot is capped below end.
    assert _silence_action(SILENCE_END_S, 0) == "end"
    assert max_prompts == 2  # 10/30 config → prompts at 10s and 20s


def test_silence_config_matches_spec():
    assert SILENCE_PROMPT_EVERY_S == 10.0
    assert SILENCE_END_S == 30.0


# ── Feature 1: the line-check lines exist in every language ───────────────────

def test_line_check_all_languages():
    for code in ("te", "en", "hi", "ta", "kn", "ml", "mr", "bn"):
        assert get_line_check(code), code
    assert len(LINE_CHECK) == 8
    # Unknown/None fall back to Telugu, never crash.
    assert get_line_check("zz") == get_line_check("te")
    assert get_line_check(None) == get_line_check("te")


# ── Feature 1: watchdog wiring (source-level guards) ─────────────────────────

def test_silence_watchdog_wired_into_entrypoint():
    src = inspect.getsource(__import__("agent.livekit_minimal.agent",
                                       fromlist=["entrypoint"]).entrypoint)
    # Registered on the user-state event + as a cancel-on-shutdown task.
    assert "user_state_changed" in src
    assert "_silence_watchdog" in src
    assert "_cancel_on_shutdown(_sil_task)" in src
    # Our own line-check is exempt from the reset (else it resets its own clock).
    assert "linecheck" in src
    # It ends the call by deleting the room.
    assert "call_ended_silence" in src


# ── Feature 2: lone-hello detection (pure) ───────────────────────────────────

def test_is_lone_hello():
    assert is_lone_hello("hello")
    assert is_lone_hello("Hello?")
    assert is_lone_hello("hello hello")
    assert is_lone_hello("హలో హలో")
    assert is_lone_hello("हैलो")
    # A single hello with real content is NOT a lone hello.
    assert not is_lone_hello("hello doctor")
    assert not is_lone_hello("hello I need an appointment")
    # Other backchannels are not hellos.
    assert not is_lone_hello("okay")
    assert not is_lone_hello("hmm")
    assert not is_lone_hello("")


def test_reconnect_all_languages():
    for code in ("te", "en", "hi", "ta", "kn", "ml", "mr", "bn"):
        assert get_reconnect(code), code
    assert len(RECONNECT) == 8
    assert get_reconnect("zz") == get_reconnect("te")


def test_lost_hello_count_is_three():
    assert LOST_HELLO_COUNT == 3


# ── Feature 2: 3-hello behaviour in on_user_turn_completed ───────────────────

def _agent():
    return VachanamAgent(
        instructions="x", state=SessionState(), db=None, room=None,
        calendar_service=None, meta_service=None, transfer_to="",
    )


def _msg(text):
    return SimpleNamespace(text_content=text, content=text, role="user")


@pytest.mark.asyncio
async def test_three_hellos_trigger_lost_connection(monkeypatch):
    from livekit.agents import StopResponse

    a = _agent()
    fired = {"n": 0}

    async def fake_handler():
        fired["n"] += 1

    monkeypatch.setattr(a, "_handle_lost_connection", fake_handler)

    turn = SimpleNamespace(items=[])
    # First two lone hellos: pass through (agent re-greets normally).
    await a.on_user_turn_completed(turn, _msg("hello"))
    assert a._consecutive_hellos == 1
    await a.on_user_turn_completed(turn, _msg("hello"))
    assert a._consecutive_hellos == 2
    # Third consecutive hello: StopResponse + lost-connection handler fires.
    with pytest.raises(StopResponse):
        await a.on_user_turn_completed(turn, _msg("hello"))
    assert a._consecutive_hellos == 0  # reset after firing
    # The handler is scheduled as a task — let the loop run it once.
    import asyncio
    await asyncio.sleep(0)
    assert fired["n"] == 1


@pytest.mark.asyncio
async def test_real_turn_resets_hello_counter(monkeypatch):
    a = _agent()

    async def fake_handler():
        raise AssertionError("must not fire")

    monkeypatch.setattr(a, "_handle_lost_connection", fake_handler)
    turn = SimpleNamespace(items=[])
    await a.on_user_turn_completed(turn, _msg("hello"))
    await a.on_user_turn_completed(turn, _msg("hello"))
    assert a._consecutive_hellos == 2
    # A real turn between hellos breaks the streak.
    await a.on_user_turn_completed(turn, _msg("I want an appointment tomorrow please"))
    assert a._consecutive_hellos == 0
    # Two more hellos: only 2 in a row now, no fire.
    await a.on_user_turn_completed(turn, _msg("hello"))
    await a.on_user_turn_completed(turn, _msg("hello"))
    assert a._consecutive_hellos == 2
