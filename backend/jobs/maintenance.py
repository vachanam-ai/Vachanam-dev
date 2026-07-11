"""One hourly Postgres wake for all unconditional housekeeping (FIXLOG #299).

Neon keeps compute running for 5 minutes after ANY query. So the cost of a
periodic job is not its frequency but the number of distinct wakes it causes:
four hourly jobs on different offsets = four wakes = ~20 min of compute per
hour. Running them back-to-back inside ONE wake costs ~5 min per hour instead.

Before this, `run_vobiz_cdr_sync` alone (every 3 min) pinned the compute on
permanently. These four now share a single hourly tick.

Each step is isolated: one failing job must never skip the others.
"""
import structlog

logger = structlog.get_logger()

async def run_hourly_maintenance() -> None:
    from backend.config import settings
    from backend.jobs.calendar_writer import requeue_stale_in_progress
    from backend.jobs.call_scoring import run_call_scoring
    from backend.jobs.finalize_stale_calls import run_finalize_stale_calls
    from backend.jobs.support_sla import run_sla_escalation

    steps = [
        ("requeue_stale_in_progress", requeue_stale_in_progress),
        ("finalize_stale_calls", run_finalize_stale_calls),
        ("call_scoring", run_call_scoring),
        # Support SLA escalation rides this wake (#299 — no extra Neon wake).
        ("support_sla_escalation", run_sla_escalation),
    ]

    # Same guard main.py used: CDR sync only runs when Vobiz creds exist.
    if settings.vobiz_auth_id and settings.vobiz_auth_token:
        from backend.jobs.vobiz_cdr_sync import run_vobiz_cdr_sync

        steps.append(("vobiz_cdr_sync", run_vobiz_cdr_sync))

    for name, fn in steps:
        try:
            await fn()
        except Exception as e:  # noqa: BLE001 — one failure must not skip the rest
            logger.warning("maintenance_step_failed", step=name, error=str(e)[:160])

    # Render free tier OOM-kills at 512MB (2026-07-11). One structured memory
    # sample per hourly wake makes the growth curve — steady leak vs spike at a
    # specific step — readable straight from Render logs.
    from backend.memstat import process_mem_mb

    mem = process_mem_mb()
    if mem:
        logger.info("maintenance_mem", rss_mb=mem["rss"], peak_mb=mem["peak"])

    # #306: deep health checks ride this wake — Neon is already awake, so the
    # DB probe and calendar-backlog check cost zero extra compute wakes.
    try:
        from backend.watchdog import run_watchdog_deep

        await run_watchdog_deep()
    except Exception as e:  # noqa: BLE001
        logger.warning("watchdog_deep_failed", error=str(e)[:160])
