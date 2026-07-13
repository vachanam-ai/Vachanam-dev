"""Meta (WhatsApp) service — REAL sends as of WA T4 (spec 2026-07-13).

Bridge between the booking path's display-string interface (unchanged since
the MVP1 stub, so booking code needed no edits) and wa_service. Loads the
branch + org plan in its OWN short-lived session (the caller's session is
mid-booking); every failure is swallowed with a log — RULE 4: WhatsApp is a
notification, a send failure never fails or blocks a booking.

Without META creds / a linked branch number / a gated-in plan this behaves
exactly like the old stub: logs and no-ops.
"""
from __future__ import annotations

from datetime import date, time

import structlog
from sqlalchemy import select

import backend.database as _db_module
from backend.services import wa_service, wa_templates

logger = structlog.get_logger()


class MetaService:
    """WhatsApp notification sender (real — Cloud API via wa_service)."""

    async def send_booking_confirmation(
        self,
        to: str,
        patient_name: str,
        doctor_name: str,
        clinic_name: str,
        booking_date: date,
        token_number: int,
        appointment_time: time | None = None,
        *,
        branch_id=None,
        token_id: str | None = None,
        patient_lang: str | None = None,
    ) -> None:
        """Send the booking-confirmation template with Reschedule/Cancel
        buttons. branch_id/token_id are optional for call-site compatibility —
        without branch_id there is no sender number, so it no-ops (logged)."""
        if branch_id is None:
            logger.info("wa_skipped_unconfigured", reason="no_branch_id")
            return
        try:
            from backend.models.schema import Branch, Organization

            async with _db_module.AsyncSessionLocal() as db:
                row = (
                    await db.execute(
                        select(Branch, Organization.plan)
                        .join(Organization, Organization.id == Branch.org_id)
                        .where(Branch.id == branch_id)
                    )
                ).first()
            if row is None:
                logger.warning("wa_branch_not_found", branch_id=str(branch_id))
                return
            branch, plan = row
            if not wa_service.wa_enabled(branch, plan):
                return
            template, lang, params, buttons = wa_templates.booking_confirm(
                clinic=clinic_name,
                doctor=doctor_name,
                booking_date=booking_date,
                appointment_time=appointment_time,
                token_number=token_number,
                address=branch.address,
                token_id=token_id or "",
                lang=wa_templates.template_lang(patient_lang),
            )
            await wa_service.send_template(branch, to, template, lang, params, buttons)
        except Exception as e:  # noqa: BLE001 — RULE 4: never surfaces to booking
            logger.warning("wa_confirmation_failed", error=str(e)[:200])

    async def send_doctor_notification(
        self,
        doctor_phone: str,
        patient_name: str,
        token_number: int,
        appointment_time: str | None = None,
    ) -> None:
        """Doctor pings stay out of WhatsApp scope (spec 2026-07-13: patient-
        facing only; doctors live on the dashboard/calendar). Logged no-op."""
        logger.debug(
            "wa_doctor_notification_skipped",
            doctor_last4=doctor_phone[-4:] if doctor_phone else None,
            token=token_number,
        )
