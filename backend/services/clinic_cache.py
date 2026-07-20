"""Per-clinic doctor roster + timings cache (Vinay 2026-07-20).

"cache clinic doctors and their timings per every clinic registers. so details
about them will be true and accurate all the time. make necessary actions to
decrease latency."

WHY: Neon scale-to-zero (#299, a deliberate cost saving) means the first query
after ~5 idle minutes pays a multi-second wake — and a clinic's phone rings
sporadically, so nearly every call paid it. The doctor roster is read on the
call's critical path (it builds the system prompt before the agent can speak).
Redis (Upstash) is always warm at ~1-5ms from Fly bom, so serving the roster
from cache takes that read off the critical path entirely.

ACCURACY (the explicit requirement): the cache is invalidated on EVERY write
that can change a roster or a timing — add/edit/delete doctor, and the branch
settings save. The TTL is only a backstop for a write path we failed to hook,
never the primary mechanism.

RULE 1: keys are per-branch; a clinic can only ever read its own roster.
RULE 9: doctors are clinic configuration, not patient data — no PII here.
"""
from __future__ import annotations

import json
from datetime import time
from uuid import UUID

import structlog

logger = structlog.get_logger()

# Backstop only — explicit invalidation below is what keeps this accurate.
CLINIC_CACHE_TTL_S = 900


def doctors_key(branch_id: UUID | str) -> str:
    return f"clinic:doctors:{branch_id}"


def _fmt_time(t: time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def serialize_doctors(rows) -> list[dict]:
    """ORM Doctor rows → the plain shape the agent's DoctorContext needs.

    Deliberately NOT the whole row: only what builds the prompt, so a schema
    change elsewhere can never silently poison a cached call.
    """
    return [
        {
            "id": str(d.id),
            "name": d.name,
            "specialization": d.specialization or "",
            "routing_keywords": list(d.routing_keywords or []),
            "booking_type": d.booking_type or "token",
            "is_default": bool(d.is_default_doctor),
            "working_hours_start": _fmt_time(d.working_hours_start),
            "working_hours_end": _fmt_time(d.working_hours_end),
            "available_weekdays": list(d.available_weekdays or []),
        }
        for d in rows
    ]


async def _redis():
    from backend.redis_client import get_redis  # shared client (#305: never per-call)

    return await get_redis()


async def get_doctors(branch_id: UUID | str) -> list[dict] | None:
    """Cached roster, or None on miss/any failure (caller falls back to DB)."""
    try:
        r = await _redis()
        raw = await r.get(doctors_key(branch_id))
        if not raw:
            return None
        return json.loads(raw)
    except Exception as e:  # noqa: BLE001 — cache must never break a call (RULE 8)
        logger.warning("clinic_cache_read_failed", error=str(e)[:120])
        return None


async def set_doctors(branch_id: UUID | str, doctors: list[dict]) -> None:
    try:
        r = await _redis()
        await r.set(
            doctors_key(branch_id), json.dumps(doctors), ex=CLINIC_CACHE_TTL_S
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("clinic_cache_write_failed", error=str(e)[:120])


async def invalidate(branch_id: UUID | str) -> None:
    """Drop a branch's cached roster. Call after ANY doctor/timing write —
    a stale roster would make the agent quote wrong hours (Vinay: details must
    be true and accurate all the time)."""
    try:
        r = await _redis()
        await r.delete(doctors_key(branch_id))
        logger.info("clinic_cache_invalidated", branch_id=str(branch_id))
    except Exception as e:  # noqa: BLE001
        logger.warning("clinic_cache_invalidate_failed", error=str(e)[:120])


async def load_doctors(branch_id: UUID | str, db) -> list[dict]:
    """Cache-first roster for the call path; populates the cache on a miss.

    On ANY cache failure this still returns the DB truth — the cache is an
    accelerator, never a source of truth for whether a doctor exists.
    """
    cached = await get_doctors(branch_id)
    if cached is not None:
        logger.info("clinic_cache_hit", branch_id=str(branch_id), doctors=len(cached))
        return cached

    from sqlalchemy import and_, select

    from backend.models.schema import Doctor

    rows = (
        await db.execute(
            select(Doctor).where(
                and_(Doctor.branch_id == branch_id, Doctor.status == "active")
            )
        )
    ).scalars().all()
    doctors = serialize_doctors(rows)
    await set_doctors(branch_id, doctors)
    logger.info("clinic_cache_miss_filled", branch_id=str(branch_id), doctors=len(doctors))
    return doctors


async def warm(branch_id: UUID | str, db) -> list[dict]:
    """Force-refresh from the DB (used right after a write, so the very next
    call is already warm instead of paying the miss)."""
    await invalidate(branch_id)
    return await load_doctors(branch_id, db)
