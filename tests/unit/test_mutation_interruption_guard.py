"""#361 (Vinay real reminder call 2026-07-13 04:00 UTC): a "hello?" spoken
over a booking write's quiet beat interrupted the speech handle; livekit then
discarded the COMPLETED reschedule result, the LLM claimed "not possible due
to some issue" and re-fired the tool. Guards:
  - _protect_mutation pins the handle (disallow_interruptions) and never
    raises even on an already-interrupted handle;
  - every booking-mutation tool pins + plays a filler so there is no dead
    air to talk over in the first place.
"""
import asyncio
import inspect
from types import SimpleNamespace

import pytest
from livekit.agents import StopResponse

from agent.livekit_minimal.agent import (
    VachanamAgent,
    _protect_mutation,
    _tracks_booking_lookup,
)
from agent.livekit_minimal.confirm_speech import build_booking_lookup_text
from agent.session_state import SessionState


class _Ctx:
    def __init__(self, raise_on_disallow=False):
        self.called = False
        self._raise = raise_on_disallow

    def disallow_interruptions(self):
        self.called = True
        if self._raise:
            raise RuntimeError("SpeechHandle is already interrupted")


def test_protect_mutation_pins_handle():
    ctx = _Ctx()
    _protect_mutation(ctx)
    assert ctx.called


def test_protect_mutation_survives_already_interrupted_handle():
    ctx = _Ctx(raise_on_disallow=True)
    _protect_mutation(ctx)  # must not raise — write proceeds unprotected
    assert ctx.called


def test_all_booking_mutations_are_pinned_and_covered():
    # Contract: the three tools that WRITE bookings pin the handle and speak
    # a filler before touching the DB/calendar. #429: these are the genuinely
    # slow ones (DB + Google Calendar), so the filler is now the "ఒక్క నిమిషం
    # అండి" WAIT phrase rather than the bare ack.
    for tool in ("confirm_booking", "reschedule_booking", "cancel_booking"):
        src = inspect.getsource(getattr(VachanamAgent, tool))
        assert "_protect_mutation(context)" in src, tool
        assert "_say_wait_filler(context)" in src, tool


def test_reschedule_lookup_has_filler():
    # find_my_bookings precedes every reschedule/cancel — no dead air there.
    # #429: slow enough (it once sat silent for ~a minute) to get the wait phrase.
    src = inspect.getsource(VachanamAgent.find_my_bookings)
    assert "_say_wait_filler(context)" in src
    assert "_protect_mutation(context)" in src


@pytest.mark.asyncio
async def test_booking_lookup_flag_covers_the_entire_read():
    entered = asyncio.Event()
    release = asyncio.Event()

    @_tracks_booking_lookup
    async def lookup(owner):
        entered.set()
        await release.wait()
        return "database answer"

    owner = SimpleNamespace(
        _state=SessionState(last_user_utterance="When is my appointment?")
    )
    task = asyncio.create_task(lookup(owner))
    await entered.wait()
    assert owner._state.booking_lookup_in_flight is True
    assert owner._state.booking_lookup_utterance == "When is my appointment?"
    release.set()
    assert await task == "database answer"
    assert owner._state.booking_lookup_in_flight is False
    assert owner._state.booking_lookup_utterance is None


def test_lookup_probe_is_consumed_before_pending_answer_is_superseded():
    src = inspect.getsource(VachanamAgent.on_user_turn_completed)
    assert src.index("booking_lookup_in_flight") < src.index("sess.interrupt()")
    assert "booking_lookup_probe_consumed" in src


@pytest.mark.asyncio
async def test_exact_live_failure_sequence_finishes_with_database_answer():
    """Reproduce: lookup starts -> caller says hello -> answer must still land."""
    entered = asyncio.Event()
    release = asyncio.Event()
    spoken = []
    state = SessionState(language="en")

    @_tracks_booking_lookup
    async def delayed_database_lookup(owner):
        entered.set()
        await release.wait()
        row = {
            "doctor": "Dr Rao",
            "date": "2026-08-21",
            "time": "17:00",
            "token_number": 1,
            "booking_type": "appointment",
            "status": "confirmed",
        }
        spoken.append(build_booking_lookup_text("en", row))

    fake = SimpleNamespace(
        _state=state,
        _message_text=VachanamAgent._message_text,
    )
    task = asyncio.create_task(delayed_database_lookup(fake))
    await entered.wait()

    message = SimpleNamespace(text_content="hello", content="hello", role="user")
    with pytest.raises(StopResponse):
        await VachanamAgent.on_user_turn_completed(
            fake, SimpleNamespace(items=[]), message
        )

    assert not task.cancelled()
    assert spoken == []
    release.set()
    await task
    assert spoken == ["Your appointment with Dr Rao is on 21 August at 5:00 PM."]
    assert state.booking_lookup_in_flight is False
