"""Hybrid sync/async Google Calendar write helper per booking_type.

Decision tree (spec §6.7):
  1. token-doctor  → return immediately (no per-patient Cal event for token flow)
  2. calendar_id is None (slot-doctor, no Cal configured)
     → enqueue CalendarWriteTask(status='failed_permanent') + admin alert, return
  3. appointment-doctor + calendar_id set
     → SYNC inline retry with backoff [0, 2, 5] seconds (3 attempts total)
     → on all-fail: enqueue CalendarWriteTask(status='pending') + admin alert, return

On inline success:
  - Token.google_calendar_event_id populated + committed.
  - No queue row written.

Structlog events emitted:
  - calendar_sync_retry   — per inline retry attempt that failed (warning)
  - calendar_sync_exhausted_enqueue — after all 3 inline attempts fail (error)
  - calendar_create_success — emitted inside GoogleCalendarService.create_booking_event (info)

See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.7.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, time
from typing import Optional

import structlog

from backend.models.schema import CalendarWriteTask, Doctor, Token
from backend.services.admin_alert import alert_admin
from backend.services.calendar_service import CalendarWriteFailed, GoogleCalendarService

logger = structlog.get_logger()

# Backoff seconds between inline retry attempts: 0s (immediate), 2s, 5s.
# Three delays → three attempts total.
SYNC_BACKOFF: list[int] = [0, 2, 5]


def _build_payload(
    token: Token,
    doctor: Doctor,
    calendar_id: str,
    patient_first_name: str,
    patient_phone_last4: str,
) -> dict:
    """Build the JSONB payload dict stored in CalendarWriteTask.payload_json.

    Uses token.appointment_time for the appointment start; falls back to
    midnight (00:00) if unset (should not happen for slot-doctors, but guards
    against None to avoid a crash in unexpected states).

    All fields required by both the inline Cal call and the async worker
    (backend/jobs/calendar_writer.py) are included.
    """
    appt_time: time = token.appointment_time or time(0, 0)
    appointment_dt: datetime = datetime.combine(token.date, appt_time)
    return {
        "calendar_id": calendar_id,
        "patient_first_name": patient_first_name,
        "patient_phone_last4": patient_phone_last4,
        "appointment_dt": appointment_dt.isoformat(),
        "duration_minutes": doctor.slot_duration_minutes or 30,
        "doctor_name": doctor.name,
    }


async def _enqueue_calendar_task(
    db,
    token: Token,
    operation: str,
    payload: dict,
    status: str = "pending",
) -> None:
    """Write one CalendarWriteTask row and commit.

    Called in two cases:
      - status='pending'          : inline retries exhausted, async worker will retry.
      - status='failed_permanent' : calendar_id is None, admin must act manually.

    Args:
        db:        Async SQLAlchemy session (already open, caller owns the session).
        token:     The confirmed Token object (provides branch_id + id).
        operation: 'create' | 'update' | 'delete'.
        payload:   JSONB dict to store in payload_json.
        status:    Initial row status.
    """
    db.add(
        CalendarWriteTask(
            branch_id=token.branch_id,
            token_id=token.id,
            operation=operation,
            payload_json=payload,
            status=status,
        )
    )
    await db.commit()


async def write_booking_calendar(
    db,
    token: Token,
    doctor: Doctor,
    calendar_id_or_none: Optional[str],
    patient_first_name: str = "",
    patient_phone_last4: str = "",
) -> None:
    """Hybrid Calendar write — sync inline for slot-doctor, skip for token-doctor.

    Must be called AFTER the Token row is committed to the DB (token.id must exist).

    Branch-id safety: token.branch_id propagates to every CalendarWriteTask row
    inserted here — Rule 1 satisfied.

    Args:
        db:                  Open async SQLAlchemy session.
        token:               Confirmed Token ORM instance.
        doctor:              Doctor ORM instance linked to token.
        calendar_id_or_none: Google Calendar ID resolved by the caller (doctor or branch);
                             None if neither the doctor nor branch has a calendar configured.
        patient_first_name:  PII — first name only (not logged, only stored in Cal summary).
        patient_phone_last4: Last 4 digits of patient phone (already masked by caller).

    Returns:
        None.  Errors never propagate to caller — booking succeeded regardless of Cal outcome.
        (CLAUDE.md Rule 4: Calendar failure raises inside this helper but is caught here and
        converted to an async queue enqueue so the booking is never rolled back.)
    """
    # ── Path 1: Token-doctor — no per-patient Cal event ───────────────────────
    if doctor.booking_type == "token":
        # Token-doctors use a single recurring clinic-hours event (Task 4).
        # Per-patient booking does NOT write a Cal event.
        return

    # ── Path 2: Calendar not configured for this slot-doctor ─────────────────
    if not calendar_id_or_none:
        # Enqueue immediately as failed_permanent — async worker will NOT retry
        # (status is already terminal). Admin must configure calendar and manually
        # re-process if needed.
        payload = _build_payload(
            token, doctor, "", patient_first_name, patient_phone_last4
        )
        await _enqueue_calendar_task(
            db, token, "create", payload, status="failed_permanent"
        )
        await alert_admin("calendar_not_configured", token.branch_id, token.id)
        logger.error(
            "calendar_not_configured",
            token_id=str(token.id),
            branch_id=str(token.branch_id),
            doctor_name=doctor.name,
        )
        return

    # ── Path 3: Slot-doctor with calendar_id — sync inline retry ─────────────
    payload = _build_payload(
        token, doctor, calendar_id_or_none, patient_first_name, patient_phone_last4
    )
    svc = GoogleCalendarService()
    last_err: Optional[Exception] = None

    for attempt_index, delay in enumerate(SYNC_BACKOFF):
        if delay:
            await asyncio.sleep(delay)
        try:
            event_id: str = await svc.create_booking_event(
                calendar_id=calendar_id_or_none,
                patient_first_name=patient_first_name,
                patient_phone_last4=patient_phone_last4,
                appointment_dt=datetime.fromisoformat(payload["appointment_dt"]),
                duration_minutes=payload["duration_minutes"],
                doctor_name=doctor.name,
            )
            # Inline success — write event_id to Token and commit.
            token.google_calendar_event_id = event_id
            await db.commit()
            logger.info(
                "calendar_create_success",
                token_id=str(token.id),
                branch_id=str(token.branch_id),
                event_id=event_id,
                attempt=attempt_index + 1,
            )
            return
        except CalendarWriteFailed as exc:
            last_err = exc
            logger.warning(
                "calendar_sync_retry",
                token_id=str(token.id),
                branch_id=str(token.branch_id),
                attempt_index=attempt_index,
                attempt_delay=delay,
                error=str(exc),
            )

    # ── Path 3b: All inline attempts exhausted — enqueue for async worker ────
    logger.error(
        "calendar_sync_exhausted_enqueue",
        token_id=str(token.id),
        branch_id=str(token.branch_id),
        doctor_name=doctor.name,
        error=str(last_err),
    )
    await _enqueue_calendar_task(db, token, "create", payload, status="pending")
    await alert_admin("calendar_sync_fail", token.branch_id, token.id)
