"""Tell Vinay when a clinic's voice minutes run away. Never blocks a call.

Vinay 2026-08-12: "Budget caps/alerts for everything so bymistake something
leaks we will not get hurt too much." Asked whether to hard-block a runaway, he
chose ALERT ONLY on 2026-08-13: no paying clinic is ever cut off on spend.

That is defensible because a runaway is bounded by concurrency, not unbounded.
The baseline is 3 simultaneous channels (beyond that the clinic pays
Rs500/concurrency/month), so the worst case between an overnight start and
somebody reading email is:

    3 channels x 8 hours = 24 call-hours = 1,440 minutes
    1,440 x Rs3.4-5.6/min = Rs4,900-8,100 of REAL cost, per clinic

A bad night, not an extinction event. If that ever stops being survivable, the
per-org `hard_block_on_exhaust` switch already exists in the schema and in
`billing_math.call_blocked` — turning it on is a config change, not a build.

Thresholds are multiples of the plan's INCLUDED minutes, so they scale with
what the clinic already bought instead of a flat number that means something
different on Basic than on Scale.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

import structlog
from sqlalchemy import func, select

import backend.database as _db_module
from backend.models.schema import Branch, BillingCycle, CallLog, Organization
from backend.services.billing_math import included_minutes_for

logger = structlog.get_logger()

# Multiples of included minutes. WARN is "look at this today"; RUNAWAY is
# "something is wrong right now". Both only notify.
WARN_MULTIPLE = 1.5
RUNAWAY_MULTIPLE = 3.0

# Statuses worth watching. paused/cancelled orgs are already blocked by
# call_blocked(), so minutes cannot accrue and an alert would be noise.
_WATCHED_STATUSES = ("active", "trial")


async def _cycle_minutes(db, org_id, start: date, end: date) -> float:
    """Voice minutes for an org across its branches in [start, end).

    Same metering as the overage invoice (`payments._cycle_minutes_used`) — an
    alert must never disagree with the bill it is warning about.
    """
    start_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    end_dt = datetime(end.year, end.month, end.day, tzinfo=timezone.utc)
    seconds = (
        await db.execute(
            select(func.coalesce(func.sum(CallLog.duration_seconds), 0))
            .join(Branch, Branch.id == CallLog.branch_id)
            .where(
                Branch.org_id == org_id,
                CallLog.started_at >= start_dt,
                CallLog.started_at < end_dt,
            )
        )
    ).scalar_one()
    return float(seconds or 0) / 60.0


def _breach(used: float, included: int) -> str | None:
    """Which threshold this usage has crossed, worst first."""
    if included <= 0:
        return None  # a no-voice plan has no bucket to exceed
    if used >= included * RUNAWAY_MULTIPLE:
        return "runaway"
    if used >= included * WARN_MULTIPLE:
        return "warn"
    return None


async def run_spend_watch() -> None:
    async with _db_module.AsyncSessionLocal() as db:
        orgs = (
            await db.execute(
                select(Organization).where(Organization.status.in_(_WATCHED_STATUSES))
            )
        ).scalars().all()

        for org in orgs:
            try:
                cycle = (
                    await db.execute(
                        select(BillingCycle)
                        .where(BillingCycle.org_id == org.id)
                        .order_by(BillingCycle.cycle_start.desc())
                        .limit(1)
                    )
                ).scalar_one_or_none()
                if cycle is None:
                    continue  # nothing billed yet — no cycle window to measure

                used = await _cycle_minutes(db, org.id, cycle.cycle_start, cycle.cycle_end)
                included = included_minutes_for(
                    org.plan, org.status, int(getattr(org, "minutes_adjustment", 0) or 0)
                )
                level = _breach(used, included)
                if level is None:
                    continue

                from backend.services.ops_alert import send_ops_alert

                multiple = RUNAWAY_MULTIPLE if level == "runaway" else WARN_MULTIPLE
                await send_ops_alert(
                    event=f"spend.{level}",
                    # One mail per org per cycle per level: an hourly job must
                    # not mail the same standing condition every hour.
                    dedupe_key=f"spend:{org.id}:{cycle.cycle_start}:{level}",
                    subject=(
                        f"[Vachanam] {org.name} used {used:,.0f} voice minutes "
                        f"({multiple:g}x its {included:,} included)"
                    ),
                    body=(
                        f"Organisation : {org.name}\n"
                        f"Plan         : {org.plan} ({org.status})\n"
                        f"Cycle        : {cycle.cycle_start} to {cycle.cycle_end}\n"
                        f"Included     : {included:,} minutes\n"
                        f"Used         : {used:,.0f} minutes ({used / included:.1f}x)\n"
                        f"\n"
                        f"No call has been blocked — this is notification only.\n"
                        f"If this is not real clinic traffic, check the branch's DID "
                        f"for abuse and consider setting hard_block_on_exhaust for "
                        f"this org.\n"
                    ),
                )
                logger.warning(
                    "spend_threshold_crossed",
                    org_id=str(org.id),
                    level=level,
                    used_minutes=round(used),
                    included_minutes=included,
                )
            except Exception as exc:  # noqa: BLE001 — one org must not stop the rest
                logger.warning(
                    "spend_watch_org_failed", org_id=str(org.id), error=str(exc)[:160]
                )
