"""Calendar service stub for Phase 1.

Returns fake event IDs. Real Google Calendar API wiring lands in Phase 6.
Stub emits a structlog warning on every call so it's obvious in audit logs
that no real calendar event was created.
"""
import uuid
from datetime import date, time

import structlog

logger = structlog.get_logger()


class CalendarService:
    """Stub Calendar service. Replace with GoogleCalendarService at Phase 6."""

    async def create_booking_event(
        self,
        calendar_id: str | None,
        patient_name: str,
        patient_phone: str | None,
        token_number: int,
        booking_date: date,
        appointment_time: time | None,
        doctor_name: str,
    ) -> str:
        """Create a calendar event. Returns event_id.

        Stub returns a fake UUID prefixed with 'stub-'. Real implementation
        will call Google Calendar API v3 events.insert.

        Args:
            calendar_id: Google Calendar ID (doctor or branch fallback).
            patient_name: Patient display name (NOT logged — PII).
            patient_phone: Patient phone, masked to last-4 in logs (CLAUDE.md Rule 10).
            token_number: Assigned token or slot number.
            booking_date: Date of the booking.
            appointment_time: Appointment time for slot-type doctors; None for token-type.
            doctor_name: Doctor display name for event title.

        Returns:
            Fake event ID prefixed with 'stub-' (e.g. 'stub-<uuid4>').
        """
        event_id = f"stub-{uuid.uuid4()}"
        logger.warning(
            "calendar_stub_used",
            event_id=event_id,
            calendar_id=calendar_id,
            doctor_name=doctor_name,
            token=token_number,
            booking_date=booking_date.isoformat(),
            appointment_time=appointment_time.isoformat() if appointment_time else None,
            patient_phone=patient_phone[-4:] if patient_phone else None,
        )
        return event_id
