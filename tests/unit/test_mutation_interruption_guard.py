"""#361 (Vinay real reminder call 2026-07-13 04:00 UTC): a "hello?" spoken
over a booking write's quiet beat interrupted the speech handle; livekit then
discarded the COMPLETED reschedule result, the LLM claimed "not possible due
to some issue" and re-fired the tool. Guards:
  - _protect_mutation pins the handle (disallow_interruptions) and never
    raises even on an already-interrupted handle;
  - every booking-mutation tool pins + plays a filler so there is no dead
    air to talk over in the first place.
"""
import inspect

from agent.livekit_minimal.agent import VachanamAgent, _protect_mutation


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
    # a filler before touching the DB/calendar.
    for tool in ("confirm_booking", "reschedule_booking", "cancel_booking"):
        src = inspect.getsource(getattr(VachanamAgent, tool))
        assert "_protect_mutation(context)" in src, tool
        assert "_say_lookup_filler(context)" in src, tool


def test_reschedule_lookup_has_filler():
    # find_my_bookings precedes every reschedule/cancel — no dead air there.
    src = inspect.getsource(VachanamAgent.find_my_bookings)
    assert "_say_lookup_filler(context)" in src
