from datetime import date, time
from uuid import uuid4

import structlog

logger = structlog.get_logger()


class CalendarService:
    """Stub Google Calendar service for dev/test.

    Real impl deferred to Phase 4 onboarding. Returns fake event ID so
    confirm_booking succeeds without external dependency.
    """

    async def create_booking_event(
        self,
        calendar_id: str | None,
        patient_name: str,
        patient_phone: str,
        token_number: int,
        booking_date: date,
        appointment_time: time | None,
        doctor_name: str,
    ) -> str:
        event_id = f"stub-{uuid4()}"
        logger.warning(
            "calendar_stub_used",
            event_id=event_id,
            calendar_id=calendar_id,
            token_number=token_number,
            phone=patient_phone[-4:] if patient_phone else "unknown",
            doctor=doctor_name,
        )
        return event_id
