"""Regression tests: disconnect handler releases held-unconfirmed token via Redis DECR.

CLAUDE.md RULE 3:
  - Token held in session until patient explicitly confirms.
  - If call drops without confirmation: IMMEDIATELY release via redis.decr().
  - DECR is rollback only — confirmed tokens are NEVER released.

These two tests verify the invariants on release_token_on_disconnect() which is
the function called from both run_pipeline's finally block and the /ws handler
in agent/server.py.
"""
import pytest
from unittest.mock import AsyncMock

from agent.session_state import SessionState


@pytest.mark.asyncio
async def test_disconnect_releases_unconfirmed_token():
    """Held but unconfirmed token must be DECRed on disconnect.

    Simulates: caller assigned token (token_held=True) but call dropped before
    they said "yes" (token_confirmed=False). Expects exactly one redis.decr call
    with the token's Redis key.
    """
    from agent.bot import release_token_on_disconnect

    redis = AsyncMock()
    state = SessionState(
        token_held=True,
        token_confirmed=False,
        token_redis_key="token:d:b:2026-06-07",
        token_number=5,
    )
    await release_token_on_disconnect(state, redis)
    redis.decr.assert_awaited_once_with("token:d:b:2026-06-07")


@pytest.mark.asyncio
async def test_disconnect_keeps_confirmed_token():
    """Confirmed token must NOT be DECRed on disconnect. CLAUDE.md RULE 3.

    Simulates: caller assigned AND confirmed the booking before disconnect.
    The token is real — rolling it back would create a ghost booking.
    redis.decr must never be called.
    """
    from agent.bot import release_token_on_disconnect

    redis = AsyncMock()
    state = SessionState(
        token_held=True,
        token_confirmed=True,
        token_redis_key="k",
        token_number=5,
    )
    await release_token_on_disconnect(state, redis)
    redis.decr.assert_not_called()
