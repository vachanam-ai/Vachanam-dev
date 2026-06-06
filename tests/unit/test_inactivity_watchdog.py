"""Unit tests for the inactivity watchdog in agent.agent.

Tests verify the 30-second timeout logic by directly testing the watchdog
coroutine. No LiveKit network connections required — uses mocks for session
and a fake JobContext.
"""
import asyncio
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Import the watchdog under test
from agent.agent import _inactivity_watchdog, INACTIVITY_TIMEOUT_SECONDS
from agent.session_state import SessionState


class FakeJobContext:
    """Minimal fake JobContext — only shutdown() is needed by the watchdog."""

    def __init__(self):
        self.shutdown_called = False
        self.shutdown_reason = None

    async def shutdown(self, reason: str = "") -> None:
        self.shutdown_called = True
        self.shutdown_reason = reason


def _make_session() -> MagicMock:
    """AgentSession mock: session.say is async, session.shutdown is sync."""
    session = MagicMock()
    session.say = AsyncMock()
    # shutdown is sync per AgentSession API
    session.shutdown = MagicMock()
    return session


@pytest.mark.asyncio
async def test_inactivity_watchdog_constant_is_30():
    """INACTIVITY_TIMEOUT_SECONDS must be exactly 30 per dispatch spec."""
    assert INACTIVITY_TIMEOUT_SECONDS == 30


@pytest.mark.asyncio
async def test_inactivity_watchdog_does_not_fire_before_timeout():
    """Watchdog must NOT fire when last activity was recent (< 30s ago)."""
    session = _make_session()
    ctx = FakeJobContext()
    state = SessionState()
    last_activity = [time.monotonic()]  # just now

    call_count = 0

    async def fake_sleep(n: float) -> None:
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise asyncio.CancelledError()

    with patch("agent.agent.asyncio.sleep", side_effect=fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await _inactivity_watchdog(last_activity, session, ctx, state)

    # session.say should NOT have been called (activity was recent)
    session.say.assert_not_called()
    session.shutdown.assert_not_called()


@pytest.mark.asyncio
async def test_inactivity_watchdog_fires_after_timeout():
    """Watchdog must call session.say + session.shutdown when silence > 30s."""
    session = _make_session()
    ctx = FakeJobContext()
    state = SessionState()
    # Simulate last activity 35 seconds ago
    last_activity = [time.monotonic() - (INACTIVITY_TIMEOUT_SECONDS + 5)]

    call_count = 0

    async def fake_sleep(n: float) -> None:
        nonlocal call_count
        call_count += 1

    with patch("agent.agent.asyncio.sleep", side_effect=fake_sleep):
        # Watchdog should return (not raise) after firing
        await _inactivity_watchdog(last_activity, session, ctx, state)

    session.say.assert_called_once()
    # The said text must be clean (no markdown artefacts that ruin TTS)
    said_text: str = session.say.call_args[0][0]
    assert "**" not in said_text
    assert "#" not in said_text
    # session.shutdown called with drain=False (sync call)
    session.shutdown.assert_called_once_with(drain=False)
