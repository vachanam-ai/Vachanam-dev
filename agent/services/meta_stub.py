from datetime import date, time

import structlog

logger = structlog.get_logger()


class MetaService:
    """Stub WhatsApp Meta Cloud API service for dev/test.

    Real impl deferred to MVP2. No-op so booking flow does not block on
    WhatsApp delivery during dev calls. Fire-and-forget contract: caller
    wraps in try/except and treats any exception as a soft failure.
    """

    async def send_booking_confirmation(
        self,
        to: str,
        patient_name: str,
        doctor_name: str,
        clinic_name: str,
        booking_date: date,
        token_number: int,
        appointment_time: time | None,
    ) -> None:
        logger.warning(
            "meta_stub_used",
            to=to[-4:] if to else "unknown",
            token_number=token_number,
            doctor=doctor_name,
        )
        return None
