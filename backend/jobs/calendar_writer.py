"""APScheduler job: drain calendar_write_tasks queue with exponential backoff.

Runs every 30 seconds via IntervalTrigger registered in backend/main.py lifespan.

Lifecycle per task tick:
  1. SELECT up to BATCH=50 rows WHERE status='pending' AND next_attempt_at <= NOW()
     ordered by next_attempt_at ASC.
  2. For each task:
     a. mark status='in_progress' + commit (prevents concurrent double-processing)
     b. dispatch by operation: 'create' | 'delete' | 'update'
     c. on success: status='done' + google_event_id + Token.google_calendar_event_id
     d. on failure: attempts++ + last_error + recompute next_attempt_at + status='pending'
                    → if attempts >= MAX_ATTEMPTS: status='failed_permanent' + admin alert

Backoff schedule: BACKOFF_SECONDS = [5, 30, 300, 3600]
  attempt 1 → retry in 5s
  attempt 2 → retry in 30s
  attempt 3 → retry in 5min
  attempt 4 → retry in 60min
  attempt 5 → failed_permanent + admin alert

See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.8.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models.schema import CalendarWriteTask, Token
from backend.services.admin_alert import alert_admin
from backend.services.calendar_service import GoogleCalendarService, CalendarWriteFailed

logger = structlog.get_logger()

# Backoff deltas indexed by attempt count (1-based: after attempt 1, 2, 3, 4).
BACKOFF_SECONDS: list[int] = [5, 30, 300, 3600]

MAX_ATTEMPTS: int = 5
BATCH: int = 50


def _compute_next_attempt(attempts: int, now: datetime) -> datetime:
    """Return the datetime for the next retry based on attempt count.

    Args:
        attempts: Current attempt count AFTER the failed attempt (1-based).
                  attempt=1 → wait 5s, attempt=2 → 30s, attempt=3 → 300s, attempt=4 → 3600s.
        now:      Reference datetime (typically datetime.now(timezone.utc) at the time of failure).

    Returns:
        now + BACKOFF_SECONDS[attempts - 1].

    Raises:
        IndexError: if attempts > len(BACKOFF_SECONDS) (should not happen; callers check attempts < MAX_ATTEMPTS).
    """
    return now + timedelta(seconds=BACKOFF_SECONDS[attempts - 1])


async def _do_calendar_op(
    svc: GoogleCalendarService,
    task: CalendarWriteTask,
) -> Optional[str]:
    """Dispatch the calendar operation encoded in task.operation.

    Returns:
        Google Calendar event_id for 'create' operations; None for 'delete'/'update'.

    Raises:
        CalendarWriteFailed: on any Google API error.
        ValueError: on unknown operation string.
    """
    p = task.payload_json

    if task.operation == "create":
        return await svc.create_booking_event(
            calendar_id=p["calendar_id"],
            patient_first_name=p["patient_first_name"],
            patient_phone_last4=p["patient_phone_last4"],
            appointment_dt=datetime.fromisoformat(p["appointment_dt"]),
            duration_minutes=p["duration_minutes"],
            doctor_name=p["doctor_name"],
        )

    if task.operation == "delete":
        if task.google_event_id:
            await svc.delete_event(p["calendar_id"], task.google_event_id)
        else:
            # No event_id means the create never succeeded — nothing to delete.
            logger.warning(
                "calendar_delete_skipped_no_event_id",
                task_id=str(task.id),
            )
        return None

    if task.operation == "update":
        if not task.google_event_id:
            raise CalendarWriteFailed(
                f"update operation requires google_event_id (task {task.id})"
            )
        await svc.update_event(
            p["calendar_id"],
            task.google_event_id,
            datetime.fromisoformat(p["appointment_dt"]),
            p["duration_minutes"],
        )
        return None

    raise ValueError(f"unknown calendar operation: {task.operation!r}")


async def _process_one_task(db, task: CalendarWriteTask) -> None:
    """Process a single CalendarWriteTask within the given DB session.

    Marks in_progress → attempts the calendar op → marks done or retries.

    Each DB commit is explicit so the worker can observe progress even if
    the process is killed mid-batch.
    """
    task.status = "in_progress"
    await db.commit()

    svc = GoogleCalendarService()
    try:
        event_id = await _do_calendar_op(svc, task)
        task.status = "done"
        if event_id:
            task.google_event_id = event_id
            # Back-fill Token.google_calendar_event_id so route handlers can read it.
            token: Optional[Token] = await db.get(Token, task.token_id)
            if token is not None:
                token.google_calendar_event_id = event_id
        await db.commit()
        logger.info(
            "calendar_task_done",
            task_id=str(task.id),
            operation=task.operation,
            branch_id=str(task.branch_id),
        )

    except Exception as exc:
        task.attempts += 1
        task.last_error = str(exc)[:500]

        if task.attempts >= MAX_ATTEMPTS:
            task.status = "failed_permanent"
            await db.commit()
            await alert_admin(
                "calendar_write_failed_permanent",
                task.branch_id,
                task.token_id,
            )
            logger.error(
                "calendar_task_failed_permanent",
                task_id=str(task.id),
                attempts=task.attempts,
                error=task.last_error,
                branch_id=str(task.branch_id),
            )
        else:
            now = datetime.now(timezone.utc)
            task.next_attempt_at = _compute_next_attempt(task.attempts, now)
            task.status = "pending"
            await db.commit()
            logger.warning(
                "calendar_task_retry_scheduled",
                task_id=str(task.id),
                attempt=task.attempts,
                next_attempt_at=task.next_attempt_at.isoformat(),
                error=task.last_error,
            )


async def run_calendar_writer() -> None:
    """APScheduler entry point — drains up to BATCH pending tasks per tick.

    Opens its own AsyncSessionLocal so no session state bleeds between runs.
    Each call to _process_one_task commits independently; a failure in one
    task does not roll back others.
    """
    async with AsyncSessionLocal() as db:
        stmt = (
            select(CalendarWriteTask)
            .where(
                CalendarWriteTask.status == "pending",
                CalendarWriteTask.next_attempt_at <= datetime.now(timezone.utc),
            )
            .order_by(CalendarWriteTask.next_attempt_at.asc())
            .limit(BATCH)
        )
        result = await db.execute(stmt)
        tasks = result.scalars().all()

        if not tasks:
            return

        logger.info("calendar_writer_tick", pending_count=len(tasks))
        for task in tasks:
            await _process_one_task(db, task)
