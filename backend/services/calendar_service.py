"""Real Google Calendar service. Replaces calendar_stub.

Auth: service-account JSON (Option A).
  - Production: GOOGLE_SA_JSON_B64 env var (base64-encoded JSON), decoded at boot to /tmp/google-sa.json.
  - Dev: GOOGLE_APPLICATION_CREDENTIALS env var pointing to google-service-account.json in repo root.

Scope: https://www.googleapis.com/auth/calendar.events (least privilege — CLAUDE.md Rule 1 / spec §6.2).

PII rules (CLAUDE.md Rule 10 / spec §6.4):
  - Event summary: "Apt — {first_name} (xx{last4})" — never full phone.
  - Event description: always empty string.

All sync googleapiclient calls are wrapped in asyncio.to_thread so the FastAPI
event loop is never blocked (spec §6.4 note).

See docs/superpowers/specs/2026-06-08-calendar-and-receptionist-pwa-design.md §6.
"""
from __future__ import annotations

import asyncio
import base64
from datetime import date as _date
from datetime import datetime, time, timedelta
from pathlib import Path
from typing import Optional

import structlog
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from backend.config import settings

logger = structlog.get_logger()

# RFC5545 weekday codes indexed by ISO weekday integer (0=Monday)
WEEKDAY_TO_RFC5545: dict[int, str] = {
    0: "MO",
    1: "TU",
    2: "WE",
    3: "TH",
    4: "FR",
    5: "SA",
    6: "SU",
}

_SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


class CalendarNotConfiguredError(Exception):
    """Raised when calendar_id is None — branch or doctor has not set up Google Calendar."""


class CalendarWriteFailed(Exception):
    """Wraps any underlying Google API failure.

    Caller (booking_calendar.py or calendar_writer.py) decides whether to
    fail the booking inline or enqueue for async retry.
    """


class GoogleCalendarService:
    """Real Google Calendar v3 service via service-account credentials.

    Instantiate once at application startup (or per-request for simplicity in
    background jobs — the token is cached by google-auth).

    Args:
        sa_json_path: Explicit path to service-account JSON. If None, resolved
            from settings (see _resolve_sa_path). Pass a path in tests to avoid
            touching settings.
    """

    def __init__(self, sa_json_path: Optional[str] = None) -> None:
        path = sa_json_path or self._resolve_sa_path()
        creds = service_account.Credentials.from_service_account_file(
            path, scopes=_SCOPES
        )
        # cache_discovery=False avoids file-system cache permission issues on Render/Fly.
        self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)

    @staticmethod
    def _resolve_sa_path() -> str:
        """Resolve the service-account JSON path from settings.

        Production: settings.google_sa_json_b64 is set → decode to /tmp/google-sa.json.
        Dev: settings.google_application_credentials points to the local JSON file.
        """
        if settings.google_sa_json_b64:
            tmp = Path("/tmp/google-sa.json")
            if not tmp.exists():
                tmp.write_bytes(base64.b64decode(settings.google_sa_json_b64))
            return str(tmp)
        return settings.google_application_credentials

    # ── SLOT-DOCTOR PATH ──────────────────────────────────────────────────────

    async def create_booking_event(
        self,
        *,
        calendar_id: Optional[str],
        patient_first_name: str,
        patient_phone_last4: str,
        appointment_dt: datetime,
        duration_minutes: int,
        doctor_name: str,
    ) -> str:
        """Create a per-patient blocking event for a slot-based booking.

        Only called for doctor.booking_type='appointment'. Token-doctor bookings
        do NOT invoke this method (spec §6.5).

        PII rules enforced here:
        - Summary: "Apt — {first_name} (xx{last4})"  — no full phone, no medical details.
        - Description: "" (empty string).

        Args:
            calendar_id: Google Calendar ID. If None raises CalendarNotConfiguredError.
            patient_first_name: Patient first name (not logged — PII).
            patient_phone_last4: Last 4 digits of patient phone (already masked by caller).
            appointment_dt: Naive or tz-aware datetime of appointment start (IST).
            duration_minutes: Slot duration in minutes.
            doctor_name: Doctor display name for event summary.

        Returns:
            Google Calendar event ID string.

        Raises:
            CalendarNotConfiguredError: calendar_id is None.
            CalendarWriteFailed: Google API returned an error.
        """
        if not calendar_id:
            raise CalendarNotConfiguredError(
                "calendar_id is None — branch or doctor has not configured Google Calendar"
            )

        end_dt = appointment_dt + timedelta(minutes=duration_minutes)
        body = {
            # Doctor name in the summary: on a SHARED clinic calendar (several
            # doctors, no per-doctor calendar_id yet) an unattributed "Apt —"
            # reads as busy time for EVERY doctor (Vinay screenshot 2026-07-14,
            # FIXLOG #364). RULE 9: first name + last4 + doctor only.
            "summary": (
                f"Apt — {patient_first_name} (xx{patient_phone_last4})"
                f" · {doctor_name}" if doctor_name else
                f"Apt — {patient_first_name} (xx{patient_phone_last4})"
            ),
            "description": "",
            "start": {
                "dateTime": appointment_dt.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
        }

        try:
            event = await asyncio.to_thread(
                lambda: self._service.events()
                .insert(calendarId=calendar_id, body=body)
                .execute()
            )
            logger.info(
                "calendar_create_success",
                calendar_id=calendar_id,
                event_id=event["id"],
                doctor_name=doctor_name,
                patient_phone=f"xx{patient_phone_last4}",
            )
            return event["id"]
        except HttpError as exc:
            logger.error(
                "calendar_create_failed",
                calendar_id=calendar_id,
                doctor_name=doctor_name,
                error=str(exc),
            )
            raise CalendarWriteFailed(str(exc)) from exc
        except Exception as exc:
            # B6: non-HttpError failures (socket timeout, google.auth token
            # refresh error, SSL error during events().insert) must ALSO surface
            # as CalendarWriteFailed. Otherwise they sail past every
            # `except CalendarWriteFailed` wrapper: the retry/enqueue loop in
            # write_booking_calendar can't catch them, the walk-in route 500s
            # AFTER commit, and no CalendarWriteTask is enqueued (the event is
            # silently never created).
            logger.error(
                "calendar_create_failed_unexpected",
                calendar_id=calendar_id,
                doctor_name=doctor_name,
                error=str(exc),
                error_type=type(exc).__name__,
            )
            raise CalendarWriteFailed(str(exc)) from exc

    # ── TOKEN-DOCTOR PATH ─────────────────────────────────────────────────────

    async def upsert_doctor_hours_event(
        self,
        *,
        calendar_id: str,
        doctor_name: str,
        working_hours_start: time,
        working_hours_end: time,
        available_weekdays: list[int],
        existing_event_id: Optional[str],
    ) -> str:
        """Create or update a recurring 'clinic hours' event for a token-based doctor.

        Token-doctors do not generate per-patient events. Instead, a single recurring
        event marks when the doctor is in clinic — for calendar visibility only.

        The event recurs weekly on the specified weekdays (RRULE:FREQ=WEEKLY;BYDAY=...).
        Anchor date = today; recurrence has no end date.

        Args:
            calendar_id: Google Calendar ID to write to.
            doctor_name: Used in summary "Dr {name} — clinic hours".
            working_hours_start: Clinic start time.
            working_hours_end: Clinic end time.
            available_weekdays: ISO weekday list (0=Mon, 6=Sun).
            existing_event_id: If set, PATCH the existing event. Else INSERT.

        Returns:
            Google Calendar event ID (new or existing).

        Raises:
            CalendarWriteFailed: Google API error.
        """
        weekday_codes = ",".join(
            WEEKDAY_TO_RFC5545[w] for w in sorted(set(available_weekdays))
        )
        anchor = _date.today()
        start_dt = datetime.combine(anchor, working_hours_start)
        end_dt = datetime.combine(anchor, working_hours_end)

        body = {
            "summary": f"Dr {doctor_name} — clinic hours",
            "description": "",
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "recurrence": [f"RRULE:FREQ=WEEKLY;BYDAY={weekday_codes}"],
        }

        try:
            if existing_event_id:
                event = await asyncio.to_thread(
                    lambda: self._service.events()
                    .patch(
                        calendarId=calendar_id,
                        eventId=existing_event_id,
                        body=body,
                    )
                    .execute()
                )
            else:
                event = await asyncio.to_thread(
                    lambda: self._service.events()
                    .insert(calendarId=calendar_id, body=body)
                    .execute()
                )

            logger.info(
                "calendar_doctor_hours_upsert",
                calendar_id=calendar_id,
                event_id=event["id"],
                doctor_name=doctor_name,
                weekdays=weekday_codes,
            )
            return event["id"]
        except HttpError as exc:
            logger.error(
                "calendar_doctor_hours_failed",
                calendar_id=calendar_id,
                doctor_name=doctor_name,
                error=str(exc),
            )
            raise CalendarWriteFailed(str(exc)) from exc

    # ── SHARED HELPERS ────────────────────────────────────────────────────────

    async def delete_event(self, calendar_id: str, event_id: str) -> None:
        """Delete a calendar event.

        Treats HTTP 404 as success (event already deleted — idempotent).

        Raises:
            CalendarWriteFailed: Any non-404 Google API error.
        """
        try:
            await asyncio.to_thread(
                lambda: self._service.events()
                .delete(calendarId=calendar_id, eventId=event_id)
                .execute()
            )
            logger.info(
                "calendar_delete_success",
                calendar_id=calendar_id,
                event_id=event_id,
            )
        except HttpError as exc:
            if getattr(exc.resp, "status", None) == 404:
                # Already deleted — treat as success (idempotent)
                logger.info(
                    "calendar_delete_404_treated_as_success",
                    calendar_id=calendar_id,
                    event_id=event_id,
                )
                return
            logger.error(
                "calendar_delete_failed",
                calendar_id=calendar_id,
                event_id=event_id,
                error=str(exc),
            )
            raise CalendarWriteFailed(str(exc)) from exc

    async def update_event(
        self,
        calendar_id: str,
        event_id: str,
        new_dt: datetime,
        duration_minutes: int,
    ) -> None:
        """Patch the start/end time of an existing event.

        Raises:
            CalendarWriteFailed: Google API error.
        """
        patch_body = {
            "start": {
                "dateTime": new_dt.isoformat(),
                "timeZone": "Asia/Kolkata",
            },
            "end": {
                "dateTime": (new_dt + timedelta(minutes=duration_minutes)).isoformat(),
                "timeZone": "Asia/Kolkata",
            },
        }
        try:
            await asyncio.to_thread(
                lambda: self._service.events()
                .patch(calendarId=calendar_id, eventId=event_id, body=patch_body)
                .execute()
            )
            logger.info(
                "calendar_update_success",
                calendar_id=calendar_id,
                event_id=event_id,
            )
        except HttpError as exc:
            logger.error(
                "calendar_update_failed",
                calendar_id=calendar_id,
                event_id=event_id,
                error=str(exc),
            )
            raise CalendarWriteFailed(str(exc)) from exc


# ---------------------------------------------------------------------------
# Legacy alias: agent/tools/booking_tools.py currently instantiates CalendarService
# and calls the old signature. Provide a backward-compat shim so the old call
# path keeps working until booking_tools.py is updated (Task 3 Step 4).
# ---------------------------------------------------------------------------

class CalendarService(GoogleCalendarService):
    """Deprecated — use GoogleCalendarService directly.

    Thin shim keeping the old agent/tools/booking_tools.py call signature working
    during the transition. Will be removed once booking_tools.py is updated.
    """

    async def create_booking_event(  # type: ignore[override]
        self,
        calendar_id: Optional[str],
        patient_name: str,
        patient_phone: Optional[str],
        token_number: int,
        booking_date: _date,
        appointment_time: Optional[time],
        doctor_name: str,
        slot_duration_minutes: Optional[int] = None,
    ) -> str:
        """Legacy signature shim — delegates to real impl with PII stripping.

        B12: honor the doctor's real slot length. The shim hardcoded 30 min, so a
        slot doctor with 15/20/60-min slots got a wrong-length calendar block from
        the voice path (the walk-in path already used the real duration).
        """
        last4 = patient_phone[-4:] if patient_phone else "0000"
        first_name = patient_name.split()[0] if patient_name else "Patient"
        if not appointment_time:
            # Token-doctor path: use working_hours_start as proxy; use noon as fallback
            appointment_dt = datetime.combine(booking_date, time(12, 0))
        else:
            appointment_dt = datetime.combine(booking_date, appointment_time)

        return await super().create_booking_event(
            calendar_id=calendar_id,
            patient_first_name=first_name,
            patient_phone_last4=last4,
            appointment_dt=appointment_dt,
            duration_minutes=slot_duration_minutes or 30,
            doctor_name=doctor_name,
        )
