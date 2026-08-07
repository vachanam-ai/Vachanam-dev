"""The agent must not hang up while a booking is still being taken.

Vinay 2026-08-08, live call: "i was saying my name for booking and it hung up."

Fly logs for that call (room ...N9TL8pWUCgKc, 19:46:07Z) show
`call_ended_by_agent` — the LLM's own end_call tool, not the silence watchdog
(which logs `call_ended_silence`). So _check_end_allowed let it through.

It let it through because its only test was `token_held and not
token_confirmed`. The model routinely never calls assign_token at all —
confirm_booking reserves the token itself when it finds none held (RULE 2 is
enforced there, agent.py "if not self._state.token_held") — so across the whole
name-and-age exchange token_held is False and the guard was inert for exactly
the stretch of the call where the CALLER is doing the talking. Precisely when
they were saying their name.

caller_asked_to_book is the flag that is actually true for that window: set
when they ask, kept while they answer unrelated questions, cleared by a flat
refusal and again when a booking completes.

The second half of the same call: completion_tokens=9 on the final LLM turn — a
bare tool call with no speech — then the room deleted 1.1s later.
wait_for_playout had nothing to wait for, so the line just went dead with no
goodbye.
"""
import inspect
from unittest.mock import AsyncMock, MagicMock

import pytest

from agent.livekit_minimal.agent import VachanamAgent
from agent.session_state import SessionState

check = VachanamAgent._check_end_allowed


def _raises(state, abandon=False) -> bool:
    try:
        check(state, abandon)
        return False
    except Exception:
        return True


# ── the reported bug ─────────────────────────────────────────────────────────

def test_cannot_hang_up_while_taking_the_patients_name():
    """No token held yet — the model skipped assign_token, as it usually does."""
    s = SessionState(caller_asked_to_book=True)
    assert s.token_held is False, "the exact state the old guard missed"
    assert _raises(s), "hung up while the caller was still giving their name"


def test_the_old_token_held_test_alone_would_have_allowed_it():
    """Pins WHY the guard failed, so a future simplification back to the single
    condition fails here instead of on a patient's call."""
    s = SessionState(caller_asked_to_book=True)
    old_guard_would_block = s.token_held and not s.token_confirmed
    assert not old_guard_would_block
    assert _raises(s)


# ── the cases that must still end cleanly ────────────────────────────────────

def test_a_completed_booking_ends_normally():
    """Vinay 2026-08-07: "end call after booking appointmenet after asking is
    anything needed and user said nothing thank you." confirm_booking clears
    caller_asked_to_book on success, so this must NOT block."""
    s = SessionState(
        caller_asked_to_book=False, token_held=True,
        token_confirmed=True, any_booking_confirmed=True,
    )
    assert not _raises(s)


def test_a_caller_who_never_asked_to_book_ends_normally():
    """Someone who only asked the clinic's timings."""
    assert not _raises(SessionState())


def test_a_flat_refusal_releases_the_guard():
    """_caller_refused_outright clears the latch, so "no, leave it" then
    goodbye ends the call without needing the abandon flag."""
    s = SessionState(caller_asked_to_book=True)
    s.caller_asked_to_book = False   # what on_user_turn_completed does
    assert not _raises(s)


def test_abandon_is_the_escape_hatch():
    """Otherwise a caller who changes their mind could never get off the line."""
    s = SessionState(caller_asked_to_book=True, token_held=True)
    assert not _raises(s, abandon=True)


def test_a_held_token_still_blocks_even_with_consent_spent():
    """Both conditions are kept. A hold that outlived its latch — a retry after
    a failed confirm — must not be hung up on either."""
    s = SessionState(caller_asked_to_book=False, token_held=True,
                     token_confirmed=False)
    assert _raises(s)


def test_the_second_family_booking_is_protected_too():
    """any_booking_confirmed stays True for the rest of the call, so a guard
    written against it would go inert after the first booking. Consent is
    re-armed for the second patient; the guard must re-arm with it."""
    s = SessionState(
        caller_asked_to_book=True,      # asked again, for their child
        any_booking_confirmed=True,     # the first booking succeeded
        token_confirmed=True,           # ...and its latch is still set
    )
    assert _raises(s), "hung up midway through the second booking"


# ── the silent hangup ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_bare_tool_call_still_says_goodbye():
    """The model ended the call with no speech in the turn; the caller heard
    nothing at all before the line died."""
    agent = MagicMock(spec=VachanamAgent)
    agent._state = SessionState(language="te")
    agent._lang_code = "te"
    agent._room = MagicMock(name="room")
    agent._room.name = "call-test"

    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.session.current_speech = None          # nothing playing
    ctx.session.say = AsyncMock()
    ctx.wait_for_playout = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        fake_api = MagicMock()
        fake_api.LiveKitAPI.return_value.room.delete_room = AsyncMock()
        fake_api.LiveKitAPI.return_value.aclose = AsyncMock()
        mp.setattr("agent.livekit_minimal.agent.api", fake_api)
        await VachanamAgent.end_call.__wrapped__(agent, ctx)

    assert ctx.session.say.await_count == 1, "hung up without a goodbye"
    spoken = ctx.session.say.await_args.args[0]
    assert spoken and spoken.strip(), "said an empty goodbye"


@pytest.mark.asyncio
async def test_a_goodbye_already_playing_is_not_doubled():
    """When the model DID speak, saying it again would talk over itself."""
    agent = MagicMock(spec=VachanamAgent)
    agent._state = SessionState(language="te")
    agent._lang_code = "te"
    agent._room = MagicMock()
    agent._room.name = "call-test"

    ctx = MagicMock()
    ctx.session = MagicMock()
    ctx.session.current_speech = MagicMock()   # goodbye already speaking
    ctx.session.say = AsyncMock()
    ctx.wait_for_playout = AsyncMock()

    with pytest.MonkeyPatch.context() as mp:
        fake_api = MagicMock()
        fake_api.LiveKitAPI.return_value.room.delete_room = AsyncMock()
        fake_api.LiveKitAPI.return_value.aclose = AsyncMock()
        mp.setattr("agent.livekit_minimal.agent.api", fake_api)
        await VachanamAgent.end_call.__wrapped__(agent, ctx)

    ctx.session.say.assert_not_awaited()


def test_a_failed_goodbye_never_blocks_the_hangup():
    """RULE 8. TTS trouble must not leave the caller stuck on a finished call."""
    src = inspect.getsource(VachanamAgent.end_call)
    goodbye = src.split("current_speech")[1].split("wait_for_playout")[0]
    assert "except Exception" in goodbye


def test_the_end_is_logged_with_enough_state_to_diagnose():
    """The 08-08 call could only be diagnosed as far as "the model did it".
    Flags, not utterances — RULE 9."""
    src = inspect.getsource(VachanamAgent.end_call)
    assert "asked_to_book" in src
    assert "last_user_utterance" not in src, "would put a spoken name in logs"
