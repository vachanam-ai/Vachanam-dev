"""Meta (WhatsApp) service stub. WhatsApp deferred to MVP2.

Stub logs and no-ops. Real Meta Cloud API integration is post-MVP1.
Stub emits a structlog warning so it's obvious no WhatsApp message was sent.
"""
from datetime import date, time

import structlog

logger = structlog.get_logger()


class MetaService:
    """Stub WhatsApp service. Real integration in MVP2."""

    async def send_booking_confirmation(
        self,
        to: str,
        patient_name: str,
        doctor_name: str,
        clinic_name: str,
        booking_date: date,
        token_number: int,
        appointment_time: time | None = None,
    ) -> None:
        """Send patient WhatsApp confirmation. Stub no-ops + logs.

        Args:
            to: Patient phone number in E.164 format (masked to last-4 in logs).
            patient_name: Patient display name (NOT logged — PII).
            doctor_name: Doctor display name.
            clinic_name: Branch/clinic name for message body.
            booking_date: Date of booking.
            token_number: Assigned token or slot number.
            appointment_time: Appointment time for slot-type; None for token-type.
        """
        logger.warning(
            "whatsapp_stub_skipped",
            to_last4=to[-4:] if to else None,
            doctor_name=doctor_name,
            clinic_name=clinic_name,
            token=token_number,
            booking_date=booking_date.isoformat() if booking_date else None,
        )

    async def send_doctor_notification(
        self,
        doctor_phone: str,
        patient_name: str,
        token_number: int,
        appointment_time: str | None = None,
    ) -> None:
        """Notify doctor of new booking. Stub no-ops + logs.

        Args:
            doctor_phone: Doctor's WhatsApp number (masked to last-4 in logs).
            patient_name: Patient display name (NOT logged — PII).
            token_number: Assigned token or slot number.
            appointment_time: Formatted time string, e.g. "14:30" (optional).
        """
        logger.warning(
            "whatsapp_doctor_notification_stub_skipped",
            doctor_phone_last4=doctor_phone[-4:] if doctor_phone else None,
            token=token_number,
        )
