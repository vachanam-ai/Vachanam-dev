"""RULE 3 (held token dies with its call) — LIVE LiveKit path coverage.

The old RULE 3 regression test imported `agent.bot.release_token_on_disconnect`,
which belonged to the retired Pipecat path (deleted in iter1 #107). This restores
behavioral coverage on the production LiveKit path: VachanamAgent._release_hold
must DECR a SLOT hold that won't become a booking, and must NEVER DECR a TOKEN
hold (the token counter is the queue sequence — a DECR would re-issue a number).

test_audit_voice.py covers the audit *row* on disconnect but explicitly mocks
Redis (no DECR); this proves the actual capacity rollback.
"""
import uuid
from datetime import date

import pytest

from agent.livekit_minimal.agent import VachanamAgent

pytestmark = pytest.mark.asyncio


async def test_release_hold_decrements_slot_hold(redis):
    """A held SLOT reservation that fails to confirm must be released (DECR)."""
    slot_key = f"slot:{uuid.uuid4()}:{uuid.uuid4()}:{date.today()}:1030"
    await redis.set(slot_key, 1)  # one outstanding hold

    await VachanamAgent._release_hold({"redis_key": slot_key, "success": True})

    assert int(await redis.get(slot_key)) == 0  # RULE 3: hold released


async def test_release_hold_never_decrements_token_counter(redis):
    """A TOKEN hold must NOT be decremented — the counter is the queue sequence;
    a DECR would hand the next patient an already-issued number."""
    token_key = f"token:{uuid.uuid4()}:{uuid.uuid4()}:{date.today()}"
    await redis.set(token_key, 5)

    await VachanamAgent._release_hold({"redis_key": token_key, "success": True})

    assert int(await redis.get(token_key)) == 5  # unchanged — never reissued


async def test_release_hold_never_pushes_below_zero(redis):
    """An absent/zero slot key must not go negative (guard against -1 -> ghost)."""
    slot_key = f"slot:{uuid.uuid4()}:{uuid.uuid4()}:{date.today()}:0900"
    # key absent entirely
    await VachanamAgent._release_hold({"redis_key": slot_key})
    assert (await redis.get(slot_key)) in (None, "0")
