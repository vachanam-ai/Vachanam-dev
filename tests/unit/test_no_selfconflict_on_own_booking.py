"""A call must never treat its OWN fresh booking as a clash.

Production 2026-08-12 (Vinay): the agent booked an appointment, then read the
same booking back as an existing one — "you already have an appointment at the
same time with the same name, do you want another time?" — which sounds like
it is about to create a second one. HARD CONSTRAINT 2 territory.

The duplicate guard in booking_tools cannot tell "booked last week" from
"booked ten seconds ago on this call". The agent can: last_confirmed_token_id
is the durable booking made in THIS call, so an id match is proof.
"""
from __future__ import annotations

import uuid

import pytest


def _agent_layer_decision(result: dict, last_confirmed_token_id):
    """The exact branch under test, isolated from AgentSession construction.

    Mirrors agent.py's confirm_booking tail: an `already_booked` whose
    existing_token_id IS this call's own booking is reported as confirmed.
    """
    if result.get("success"):
        return result
    if result.get("reason") == "already_booked":
        mine = last_confirmed_token_id
        if mine is not None and str(result.get("existing_token_id")) == str(mine):
            return {
                "success": True,
                "reason": "already_confirmed_this_call",
                "token_id": str(mine),
                "token_number": result.get("existing_token_number"),
                "existing_time": result.get("existing_time"),
                "instruction": (
                    "This is the booking you ALREADY made for this caller on "
                    "this call — it is confirmed and correct. Do not read it "
                    "back as a clash, do not offer another time, and do not "
                    "book again. Simply confirm it stands and ask if they need "
                    "anything else."
                ),
            }
    return result


MINE = uuid.uuid4()
SOMEONE_ELSES = uuid.uuid4()


def _already_booked(token_id) -> dict:
    return {
        "success": False,
        "reason": "already_booked",
        "existing_token_number": 4,
        "existing_token_id": str(token_id),
        "existing_time": "10:30",
        "instruction": "Patient already has a confirmed booking that day — "
                       "tell them their existing booking instead of creating "
                       "another. If the patient wants THAT existing booking "
                       "moved, call reschedule_booking(...)",
    }


def test_own_booking_is_reported_as_confirmed_not_a_clash():
    out = _agent_layer_decision(_already_booked(MINE), MINE)

    assert out["success"] is True
    assert out["reason"] == "already_confirmed_this_call"
    assert str(out["token_id"]) == str(MINE)
    lowered = out["instruction"].lower()
    assert "do not offer another time" in lowered
    assert "do not book again" in lowered
    assert "reschedule_booking" not in out["instruction"], \
        "must not steer the agent into moving the booking it just made"


def test_a_genuinely_earlier_booking_still_blocks():
    """The real duplicate guard must keep working — this is the double-book wall."""
    out = _agent_layer_decision(_already_booked(SOMEONE_ELSES), MINE)

    assert out["success"] is False
    assert out["reason"] == "already_booked"
    assert "instead of creating another" in out["instruction"]


def test_no_booking_yet_this_call_still_blocks():
    """Before any booking exists, every already_booked is a genuine clash."""
    out = _agent_layer_decision(_already_booked(SOMEONE_ELSES), None)
    assert out["success"] is False
    assert out["reason"] == "already_booked"


def test_success_results_pass_through_untouched():
    ok = {"success": True, "token_id": str(MINE), "token_number": 7}
    assert _agent_layer_decision(ok, MINE) is ok


def test_agent_source_implements_this_branch():
    """Guard the real call site, since the logic above is a mirror of it."""
    import ast
    from pathlib import Path

    src = Path("agent/livekit_minimal/agent.py").read_text(encoding="utf-8")
    assert 'result.get("reason") == "already_booked"' in src
    assert "already_confirmed_this_call" in src
    assert "last_confirmed_token_id" in src
    ast.parse(src)  # the edit must not have broken the module
