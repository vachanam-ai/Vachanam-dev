"""One outbound call to a patient at a time, across every job that dials.

Vinay 2026-08-08: "i think for remainder calls 2 calls triggering at same time
for 1 appointment. instead of just triggering 1 call."

FOUR independent jobs dial patients — pre_appt_reminder, next_visit_followup,
cascade_rebook and question_callback — and none of them knew about the others.
Each creates a dispatch into a fresh `{kind}-{uuid4}` room, so there is no
natural key anywhere that says "this patient is already being rung". A patient
with an appointment reminder and a treatment follow-up due in the same minute
gets two calls at once, and on a retry a single job can do it alone.

The guard is a Redis SET NX per phone number, not per token: what a patient
experiences is two phones ringing, and they do not care which job caused it.

WHY A SHORT TTL AND NOT A DELETE. The lock is a collision window, not a
lifecycle — nothing here observes when a call ends, and a lock that had to be
released explicitly would strand the number for good if a worker died
mid-dispatch. It expires on its own, and the worst case is one skipped tick.

RULE 8: Redis trouble FAILS OPEN. A reminder that goes out twice is annoying;
a reminder that never goes out because Redis hiccuped is a missed appointment,
and the patient paid for that slot.

RULE 9: the key holds the last 10 digits, which is what every other phone
lookup in the codebase keys on, and never a name.
"""
from __future__ import annotations

import structlog

logger = structlog.get_logger()

# Long enough to cover ringing plus a short call, short enough that a crashed
# dispatch never blocks the next legitimate one for more than a couple of
# minutes. Reminders run on a 60s tick, so this spans a few ticks.
LOCK_TTL_SECONDS = 180


def _last10(phone: str | None) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


def lock_key(phone: str | None) -> str:
    return f"outbound:call:{_last10(phone)}"


async def claim_outbound_call(phone: str | None, kind: str) -> bool:
    """True when THIS job may dial ``phone`` now.

    False means another outbound call to that number is already in flight and
    this one must be skipped — the caller leaves its own 'sent' flag unset so
    the next tick retries, exactly as it does for a failed dispatch.
    """
    key = lock_key(phone)
    if not _last10(phone):
        return True  # nothing to key on; never block a dial over a parse miss
    try:
        from backend.redis_client import drop, get_redis

        try:
            got = await get_redis().set(key, kind, nx=True, ex=LOCK_TTL_SECONDS)
        except Exception:
            drop()  # never ride a poisoned socket forever (#305)
            raise
    except Exception as e:  # noqa: BLE001 — RULE 8: fail OPEN, see module docstring
        logger.warning("outbound_guard_unavailable", kind=kind, error=str(e)[:200])
        return True
    if not got:
        logger.info("outbound_call_skipped_already_dialing", kind=kind, key=key)
        return False
    return True


async def release_outbound_call(phone: str | None) -> None:
    """Hand the number back early — only for a dispatch that FAILED, so a
    genuine retry is not made to wait out the TTL."""
    if not _last10(phone):
        return
    try:
        from backend.redis_client import get_redis

        await get_redis().delete(lock_key(phone))
    except Exception as e:  # noqa: BLE001 — best effort; the TTL is the backstop
        logger.warning("outbound_guard_release_failed", error=str(e)[:200])
