"""One outbound call to a patient at a time, across every job that dials.

Vinay 2026-08-08: "i think for remainder calls 2 calls triggering at same time
for 1 appointment. instead of just triggering 1 call."

FOUR independent jobs dial patients — pre_appt_reminder, next_visit_followup,
cascade_rebook and question_callback — and none of them knew about the others.
Each creates a dispatch into a fresh `{kind}-{uuid4}` room, so there is no
natural key anywhere that says "this patient is already being rung". A patient
with an appointment reminder and a treatment follow-up due in the same minute
gets two calls at once, and on a retry a single job can do it alone.

The guard is a Redis SET NX per physical phone number, not per token or branch.
A handset cannot answer two clinics at once; scoping the key to a branch caused
the second reminder to hit BUSY and then race its retry state. Different phone
numbers still dispatch concurrently.

WHY A SHORT TTL PLUS RENEWAL. The assigned worker renews the claim throughout
the call and releases it at shutdown. The TTL remains the crash backstop, so a
dead worker cannot strand the handset. Renewal and release both compare the
unique owner atomically: a stale worker cannot extend or delete a newer lock.

RULE 8: Redis trouble FAILS OPEN. A reminder that goes out twice is annoying;
a reminder that never goes out because Redis hiccuped is a missed appointment,
and the patient paid for that slot.

RULE 9: the key contains only an HMAC fingerprint, never phone digits or a name.
"""
from __future__ import annotations

import asyncio
import hashlib
import hmac
import uuid

import structlog

from backend.config import settings

logger = structlog.get_logger()

# Long enough to cover ringing plus a short call, short enough that a crashed
# dispatch never blocks the next legitimate one for more than a couple of
# minutes. Reminders run on a 60s tick, so this spans a few ticks.
LOCK_TTL_SECONDS = 180
LOCK_RENEW_SECONDS = LOCK_TTL_SECONDS // 3

_RENEW_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('expire', KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_LUA = """
if redis.call('get', KEYS[1]) == ARGV[1] then
  return redis.call('del', KEYS[1])
end
return 0
"""


def _last10(phone: str | None) -> str:
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    return digits[-10:] if len(digits) >= 10 else ""


def lock_key(phone: str | None, branch_id: object | None = None) -> str:
    """Stable, privacy-safe key shared by every clinic dialing this handset."""
    del branch_id  # compatibility for existing callers; scope is intentionally global
    fingerprint = hmac.new(
        settings.jwt_secret.encode("utf-8"),
        _last10(phone).encode("ascii"),
        hashlib.sha256,
    ).hexdigest()[:24]
    return f"outbound:call:{fingerprint}"


def _valid_claim(key: str | None, owner: str | None) -> bool:
    """Accept only this guard's privacy-safe keys and bounded opaque owners."""
    if not isinstance(key, str) or not isinstance(owner, str):
        return False
    prefix = "outbound:call:"
    suffix = key.removeprefix(prefix)
    return (
        key.startswith(prefix)
        and len(suffix) == 24
        and all(ch in "0123456789abcdef" for ch in suffix)
        and bool(owner)
        and len(owner) <= 100
    )


async def claim_outbound_call(
    phone: str | None, kind: str, branch_id: object | None = None
) -> str | None:
    """Return this claim's ownership token when the job may dial ``phone``.

    None means another outbound call to that number is already in flight and
    this one must be skipped — the caller leaves its own 'sent' flag unset so
    the next tick retries, exactly as it does for a failed dispatch.

    Redis failure and unkeyable numbers fail open with a local token. Releasing
    such a token is harmless; compare-and-delete will not match any Redis lock.
    """
    key = lock_key(phone, branch_id)
    owner = f"{kind}:{uuid.uuid4().hex}"
    if not _last10(phone):
        return owner  # nothing to key on; never block a dial over a parse miss
    try:
        from backend.redis_client import drop, get_redis

        try:
            got = await get_redis().set(key, owner, nx=True, ex=LOCK_TTL_SECONDS)
        except Exception:
            drop()  # never ride a poisoned socket forever (#305)
            raise
    except Exception as e:  # noqa: BLE001 — RULE 8: fail OPEN, see module docstring
        logger.warning("outbound_guard_unavailable", kind=kind, error=str(e)[:200])
        return owner
    if not got:
        logger.info("outbound_call_skipped_already_dialing", kind=kind, key=key)
        return None
    return owner


async def release_outbound_call(
    phone: str | None, owner: str | None, branch_id: object | None = None
) -> None:
    """Release a failed dispatch's lock only while this caller still owns it."""
    if not _last10(phone) or not owner:
        return
    await release_outbound_claim(lock_key(phone, branch_id), owner)


async def renew_outbound_claim(key: str | None, owner: str | None) -> bool | None:
    """Extend this exact owner's lock; false means ownership has been lost."""
    if not _valid_claim(key, owner):
        return False
    try:
        from backend.redis_client import drop, get_redis

        try:
            renewed = await get_redis().eval(
                _RENEW_LUA, 1, key, owner, LOCK_TTL_SECONDS
            )
        except Exception:
            drop()
            raise
    except Exception as exc:  # noqa: BLE001 — active calls fail open
        logger.warning("outbound_guard_renew_failed", error=str(exc)[:200])
        return None
    return bool(renewed)


async def release_outbound_claim(key: str | None, owner: str | None) -> bool:
    """Atomically release ``key`` only if ``owner`` still owns it."""
    if not _valid_claim(key, owner):
        return False
    try:
        from backend.redis_client import get_redis

        return bool(await get_redis().eval(_RELEASE_LUA, 1, key, owner))
    except Exception as exc:  # noqa: BLE001 — TTL is the crash/release backstop
        logger.warning("outbound_guard_release_failed", error=str(exc)[:200])
        return False


async def maintain_outbound_claim(key: str | None, owner: str | None) -> None:
    """Keep a live worker's claim renewed until cancelled or ownership is lost."""
    if not _valid_claim(key, owner):
        logger.warning("outbound_guard_invalid_claim_metadata")
        return
    while True:
        renewed = await renew_outbound_claim(key, owner)
        if renewed is False:
            logger.warning("outbound_guard_ownership_lost", key=key)
            return
        await asyncio.sleep(LOCK_RENEW_SECONDS)


async def finish_outbound_claim(
    renewal_task: asyncio.Task | None, key: str | None, owner: str | None
) -> None:
    """Stop renewal, then release only this worker's still-owned claim."""
    if renewal_task is not None:
        renewal_task.cancel()
        try:
            await renewal_task
        except (asyncio.CancelledError, Exception):
            pass
    await release_outbound_claim(key, owner)
