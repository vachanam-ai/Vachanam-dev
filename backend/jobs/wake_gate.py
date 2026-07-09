"""Keep Postgres asleep when there is no work to do (FIXLOG #299).

Neon suspends its compute only after 5 minutes of TOTAL query silence, and that
timeout is not shortenable. So a scheduler that polls every 30-60s pins the
database awake 24/7 — roughly $19/month at 0.25 CU even with zero calls, which
is what exhausted the free tier on 2026-07-09 and took the clinic offline.

These helpers let a job decide, using Redis alone, whether it must touch
Postgres at all. One primitive, used by every gated job:

  The job records WHEN its next item actually becomes due, recomputed from the
  database on each real pass. Ticks before that moment never touch Postgres.

It is SCHEDULE-driven, not producer-driven, on purpose: a row inserted by any
path we forgot to instrument is still picked up on the next real pass. Writers
merely clear the cached time to make a fresh row prompt — never to make it
correct.

FAIL-OPEN, ALWAYS. If Redis is unreachable, slow, or the key is missing, every
helper answers "yes, go check Postgres". A missed reminder costs a patient their
appointment; an extra query costs a fraction of a cent. Correctness first.

A SAFETY_SECONDS ceiling caps how long a job may skip Postgres, so a stale or
mis-set due time still self-heals within the hour.
"""
import time

import redis.asyncio as aioredis
import structlog

from backend.config import settings

logger = structlog.get_logger()

# Never let a job sleep longer than this without one real Postgres pass, so a
# lost producer signal self-heals. One wake/hour ≈ 5 min of compute ≈ $1.6/mo.
SAFETY_SECONDS = 3600

_NEXT_AT_KEY = "wake:next_at:{job}"


def _redis():
    """Fresh client per call — a module-level client outlives its event loop."""
    return aioredis.from_url(settings.redis_url, decode_responses=True)


# ── time-scheduled work ─────────────────────────────────────────────────────
async def set_next_at(job: str, epoch: float | None) -> None:
    """Record when `job` next has real work. None ⇒ nothing pending; we still
    re-check within SAFETY_SECONDS. The value is capped so no job can sleep
    past the safety ceiling."""
    ceiling = time.time() + SAFETY_SECONDS
    value = ceiling if epoch is None else min(float(epoch), ceiling)
    try:
        async with _redis() as r:
            await r.set(_NEXT_AT_KEY.format(job=job), value)
    except Exception as e:  # noqa: BLE001
        logger.warning("wake_gate_set_next_failed", job=job, error=str(e)[:120])


async def clear_next_at(job: str) -> None:
    """A writer changed the schedule (booking made / moved / cancelled), so the
    cached next-due time is stale. Drop it: the next tick recomputes from
    Postgres — which is already awake, since the writer just used it."""
    try:
        async with _redis() as r:
            await r.delete(_NEXT_AT_KEY.format(job=job))
    except Exception as e:  # noqa: BLE001
        logger.warning("wake_gate_clear_next_failed", job=job, error=str(e)[:120])


async def should_run_scheduled(job: str) -> bool:
    """True when the next item is due (or we simply don't know). Fail-open."""
    try:
        async with _redis() as r:
            raw = await r.get(_NEXT_AT_KEY.format(job=job))
        if raw is None:
            return True  # unknown ⇒ ask Postgres
        return time.time() >= float(raw)
    except Exception as e:  # noqa: BLE001
        logger.warning("wake_gate_check_next_failed", job=job, error=str(e)[:120])
        return True
