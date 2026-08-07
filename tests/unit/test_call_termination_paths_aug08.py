"""Every way a call can be hung up, enumerated — so none is ever added blind.

Vinay 2026-08-08, after the mid-booking hangup: "please, this should not
happen."

The instance was fixed in #501. This file is about the CLASS. The reason that
bug existed is that `_check_end_allowed` guarded one termination path while the
codebase had six, and nothing anywhere listed them — so "can this cut a caller
off mid-sentence?" was a question no one was ever forced to answer. Twice now
in a week I have fixed one site and left an identical sibling (the affirmation
list, the sticky-consent latch, the date table in one prompt builder).

So the set is pinned. Adding a seventh way to end a call fails this test until
someone writes down what it does about a booking in progress. That is the whole
point: the test cannot verify the answer is *correct*, but it can guarantee the
question gets asked.
"""
import ast
import inspect
import pathlib

from agent.livekit_minimal import agent as agent_mod
from agent.livekit_minimal.agent import VachanamAgent, _silence_action
from agent.session_state import SessionState

SRC = pathlib.Path(agent_mod.__file__).read_text(encoding="utf-8")


def _termination_sites() -> set[str]:
    """Innermost function enclosing each room.delete_room() call."""
    stack: list[str] = []
    found: set[str] = set()

    class V(ast.NodeVisitor):
        def visit_FunctionDef(self, n):
            stack.append(n.name)
            self.generic_visit(n)
            stack.pop()

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, n):
            f = n.func
            if isinstance(f, ast.Attribute) and f.attr == "delete_room":
                found.add(">".join(stack))
            self.generic_visit(n)

    V().visit(ast.parse(SRC))
    return found


# Each entry records WHY it cannot cut off a caller who is mid-booking.
KNOWN_TERMINATIONS = {
    # Infra failure before the session exists (DB down, #298). No conversation
    # has happened, so there is no booking to interrupt. Speaks a notice first.
    "_end_call_with_notice",
    # Three consecutive lone "hello" — the caller cannot hear us, so the line
    # is already one-way. Speaks the reconnect notice first.
    "_handle_lost_connection",
    # The model's own tool. Guarded by _check_end_allowed — see the tests below
    # and test_end_call_midbooking_aug08.
    "end_call",
    # Service gate: org paused/unpaid. Runs before the booking agent starts at
    # all, on a throwaway session that only speaks the blocked line.
    "entrypoint",
    # Plan minute cap. CAN land mid-booking, deliberately — it is a billing
    # limit, and money is Vinay's call, not mine. It is not silent: cap_warning
    # is spoken 10s ahead and cap_goodbye at the end. Default 900s for
    # uncapped plans, which no legitimate call reaches.
    "entrypoint>_solo_cap_watchdog",
    # Silence. Only fires when the caller has said nothing for 30s (or 8s after
    # a COMPLETED mutation) — never while they are speaking; the watchdog holds
    # its own clock whenever user_state is "speaking".
    "entrypoint>_silence_watchdog",
}


def test_no_unreviewed_way_to_end_a_call():
    """A seventh hangup path must state what it does about a live booking."""
    found = _termination_sites()
    new = found - KNOWN_TERMINATIONS
    assert not new, (
        f"new call-termination path(s): {sorted(new)}. Every one of these can "
        f"cut a patient off mid-sentence. Decide what it does when a booking "
        f"is in progress, write that down, then add it to KNOWN_TERMINATIONS."
    )


def test_no_termination_path_was_quietly_deleted():
    """A path disappearing is also a change worth noticing — the silence
    watchdog vanishing would strand callers on a dead line forever."""
    missing = KNOWN_TERMINATIONS - _termination_sites()
    assert not missing, f"termination path(s) gone: {sorted(missing)}"


# ── the properties each guarded path depends on ──────────────────────────────

def test_silence_never_ends_a_call_while_the_caller_is_speaking():
    """The 30s window is only safe because the clock is held during speech."""
    src = inspect.getsource(agent_mod.entrypoint)
    watchdog = src.split("_silence_watchdog")[1].split("_sil_task")[0]
    assert 'u_state == "speaking"' in watchdog
    assert '"thinking", "speaking", "initializing"' in watchdog


def test_the_short_wrapup_window_needs_a_completed_mutation():
    """8s is short enough to matter. It must not be reachable mid-booking."""
    assert _silence_action(9.0, 0, closing=False) != "end", "8s cannot end a live call"
    assert _silence_action(9.0, 0, closing=True) == "end"
    # `closing` is set in exactly one place, and only after a verified write.
    assert SRC.count("closing = True") == 1
    confirm = inspect.getsource(VachanamAgent._speak_deterministic_confirm)
    assert "closing = True" in confirm, "closing moved off the post-write path"


def test_the_caller_speaking_cancels_the_wrapup_window():
    src = inspect.getsource(agent_mod.entrypoint)
    handler = src.split("_on_user_state")[1].split("_silence_watchdog")[0]
    assert "state.closing = False" in handler


def test_the_plan_cap_always_warns_before_it_cuts():
    """It is allowed to land mid-booking; it is not allowed to be silent."""
    src = inspect.getsource(agent_mod.entrypoint)
    cap = src.split("_solo_cap_watchdog")[1].split("_cap_task")[0]
    assert "cap_warning" in cap
    assert "cap_goodbye" in cap
    assert cap.index("cap_warning") < cap.index("delete_room")


def test_the_uncapped_default_never_reaches_a_real_call():
    src = inspect.getsource(agent_mod.entrypoint)
    assert "ABSOLUTE_CAP_DEFAULT = 900" in src


# ── the one path the model controls ──────────────────────────────────────────

def test_the_model_cannot_hang_up_on_a_booking_by_any_route():
    """The states an in-flight booking can actually be in, all blocked."""
    for state in (
        SessionState(caller_asked_to_book=True),                       # no token yet
        SessionState(caller_asked_to_book=True, token_held=True),      # held
        SessionState(token_held=True, token_confirmed=False),          # latch spent
        SessionState(caller_asked_to_book=True, any_booking_confirmed=True),
    ):
        try:
            VachanamAgent._check_end_allowed(state, False)
            raise AssertionError(f"end_call allowed with {state!r}")
        except AssertionError:
            raise
        except Exception:
            pass


def test_a_finished_call_can_still_hang_up():
    """The guard must not become a trap — that is its own outage."""
    VachanamAgent._check_end_allowed(SessionState(), False)
    VachanamAgent._check_end_allowed(
        SessionState(token_held=True, token_confirmed=True), False
    )
    VachanamAgent._check_end_allowed(SessionState(caller_asked_to_book=True), True)


def test_silence_still_ends_a_call_the_guard_refuses():
    """Belt and braces: if the model gets stuck refusing to hang up, the
    watchdog deletes the room directly and never consults end_call."""
    src = inspect.getsource(agent_mod.entrypoint)
    watchdog = src.split("_silence_watchdog")[1].split("_sil_task")[0]
    assert "delete_room" in watchdog
    assert "_check_end_allowed" not in watchdog
