"""Reconcile call-metering rows stranded by a crashed worker (TD-027/F6).

The voice agent writes a CallLog row at call START (duration 0) and finalizes
the real duration in its shutdown callback. If the worker is OOM-killed or
redeployed mid-call the callback never runs and the row is left at duration 0 —
undercounting that call's billable minutes to zero.

Every run: rows still at duration_seconds=0 whose started_at is older than the
grace window (no real call runs that long — the absolute call ceiling is 900s)
are finalized to a conservative fixed estimate and flagged in the log so they
can be reconciled against the telephony provider's CDRs if exact minutes matter.
"""
from datetime import datetime, timedelta, timezone

import structlog
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.config import settings
from backend.models.schema import CallLog

logger = structlog.get_logger()

# Rows older than this with duration still 0 cannot be live calls (the agent's
# absolute call ceiling is 900s) — they are crash-stranded.
STALE_GRACE_SECONDS = 3600


async def run_finalize_stale_calls() -> None:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(seconds=STALE_GRACE_SECONDS)
    estimate = max(0, int(settings.stale_call_minutes_estimate) * 60)
    async with _db_module.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(CallLog).where(
                    and_(
                        CallLog.duration_seconds == 0,
                        CallLog.started_at < cutoff,
                    )
                )
            )
        ).scalars().all()
        for row in rows:
            row.duration_seconds = estimate
            logger.warning(
                "call_log_finalized_stale",
                call_log_id=str(row.id),
                branch_id=str(row.branch_id),
                started_at=row.started_at.isoformat() if row.started_at else None,
                estimate_seconds=estimate,
            )
        if rows:
            await db.commit()
            logger.info("stale_call_logs_reconciled", count=len(rows))
