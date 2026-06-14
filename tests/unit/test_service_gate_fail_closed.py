"""iter1 #23: the agent service-block gate must FAIL CLOSED for known terminal
org states when its check raises.

Before the fix, the gate's `except` left blocked_reason=None on ANY error, so a
paused/cancelled/trial-expired org kept getting served whenever the billing/DB
lookup hiccupped. Now, if the org's last-known status is paused/cancelled/
suspended and a downstream step raises, the gate refuses the call; only genuinely
transient/unknown lookups (status never read) still fail open.
"""
import pytest

from agent.livekit_minimal.agent import _gate_failure_blocked_reason


@pytest.mark.parametrize("status", ["paused", "cancelled", "suspended", "PAUSED", "Cancelled"])
def test_terminal_status_fails_closed_on_error(status):
    """A known terminal status + a raised check → refuse (non-None blocked reason)."""
    reason = _gate_failure_blocked_reason(status)
    assert reason is not None
    assert reason.startswith("service_")


@pytest.mark.parametrize("status", [None, "", "active", "trial", "unknown_future_state"])
def test_non_terminal_or_unknown_status_fails_open(status):
    """An active/unknown/never-read status fails open so a blip never hangs up on
    a paying clinic."""
    assert _gate_failure_blocked_reason(status) is None
