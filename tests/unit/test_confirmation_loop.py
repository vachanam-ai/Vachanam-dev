"""The agent must not ask the same confirmation question over and over.

Vinay, 2026-08-03, two live calls:

    once it said doctor available at 10am shall i book appointment and when i
    say yes and it has all details like name and age it should immediately
    book. (now, it is repeating 3 times).

    and i switched to hindi and asked to reschedule. and now, it got stuck in
    a loop (you asked to reschedule appointment from 10 to 11 can i
    reschedule?) it is repeating n number of times and i ended conv because
    it is not proceeding further.

ROOT CAUSE. The mutation guards answered "have we asked the caller yet?" by
string-matching the assistant's OWN transcript against a hardcoded phrase list
per language:

    'shall i book', 'బుక్ చేయమంటారా', 'रीशेड्यूल कर दूँ', ...

But the guard's ToolError instructs the model to ask the question "in the
active language", and the model then writes it freely. Any natural rephrasing
missed the list, so:

    guard blocks -> model asks -> caller says yes -> phrase doesn't match
    -> guard blocks -> model asks the SAME question again -> forever.

Hindi is the worst case because even the same words vary in spelling (दूँ with
chandrabindu vs दूं with anusvara), which is why the Hindi reschedule never
terminated while Telugu booking merely took three tries.

FIX: `SessionState.pending_confirmation` is armed by the guard itself at the
moment it demands the question. It is language-independent and cannot drift
from what the model actually says.
"""
import inspect

import pytest

from agent.session_state import SessionState


class _FakeAgent:
    """Only the two members the detectors touch — importing the real Agent
    pulls the whole LiveKit worker in."""

    def __init__(self, state):
        self._state = state
        self.chat_ctx = type("Ctx", (), {"items": []})()

    from agent.livekit_minimal.agent import VachanamAgent as _A

    _awaiting_confirmation = _A._awaiting_confirmation
    _last_assistant_requested_booking_confirmation = (
        _A._last_assistant_requested_booking_confirmation
    )
    _last_assistant_requested_cancellation = _A._last_assistant_requested_cancellation
    _last_assistant_requested_reschedule = _A._last_assistant_requested_reschedule
    _message_text = _A._message_text


@pytest.fixture
def agent():
    return _FakeAgent(SessionState())


# ── the flag authorizes regardless of language ───────────────────────────────

def test_a_pending_book_flag_authorizes_the_next_yes(agent):
    assert agent._last_assistant_requested_booking_confirmation() is False
    agent._state.pending_confirmation = "book"
    assert agent._last_assistant_requested_booking_confirmation() is True


def test_a_pending_reschedule_flag_authorizes_the_next_yes(agent):
    """The Hindi loop: no transcript phrase matched, so this was always False."""
    agent._state.pending_confirmation = "reschedule"
    assert agent._last_assistant_requested_reschedule() is True


def test_a_pending_cancel_flag_authorizes_the_next_yes(agent):
    agent._state.pending_confirmation = "cancel"
    assert agent._last_assistant_requested_cancellation() is True


def test_the_flag_does_not_leak_across_mutation_kinds(agent):
    """Being asked "shall I book?" must never authorize a CANCEL."""
    agent._state.pending_confirmation = "book"
    assert agent._last_assistant_requested_cancellation() is False
    assert agent._last_assistant_requested_reschedule() is False


def test_no_flag_and_no_matching_phrase_still_blocks(agent):
    """The guard must stay a real guard — an unprompted tool call is refused."""
    agent._state.pending_confirmation = None
    assert agent._last_assistant_requested_booking_confirmation() is False
    assert agent._last_assistant_requested_cancellation() is False
    assert agent._last_assistant_requested_reschedule() is False


# ── the guards arm and disarm it ─────────────────────────────────────────────

def _src(name):
    from agent.livekit_minimal.agent import VachanamAgent

    return inspect.getsource(getattr(VachanamAgent, name))


# reschedule_booking is absent on purpose since 2026-08-08: it no longer
# demands a confirmation question, so there is no flag for it to arm. The rule
# below still holds for every guard that DOES ask.
@pytest.mark.parametrize("tool,kind", [
    ("confirm_booking", "book"),
    ("cancel_booking", "cancel"),
])
def test_each_guard_arms_its_flag_before_demanding_the_question(tool, kind):
    src = _src(tool)
    assert f"pending_confirmation = '{kind}'" in src, (
        f"{tool} demands a confirmation question but never arms the flag, so "
        f"the caller's yes can never authorize it — that IS the loop"
    )


@pytest.mark.parametrize("tool", ["confirm_booking", "reschedule_booking", "cancel_booking"])
def test_each_guard_disarms_once_authorized(tool):
    """A stale flag would let one "yes" authorize a mutation the caller was
    never asked about."""
    assert "pending_confirmation = None" in _src(tool)


def test_the_flag_starts_unset():
    assert SessionState().pending_confirmation is None
