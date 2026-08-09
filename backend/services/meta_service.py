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


# The ORDER our arguments go into {{1}}, {{2}}, ... per purpose.
#
# Read off the templates Vinay actually registered (2026-08-04), because
# position is all Meta gives us — there are no named parameters, so a clinic
# whose {{1}} is the patient's name and ours is the clinic's produces a message
# addressed "Hello Sri Venkateshwara". Padding a mismatch, as the generic
# fitter does, hides exactly that.
#
#   confirm     {{1}} patient · {{2}} clinic · {{3}} doctor · {{4}} date · {{5}} time
#   reschedule  {{1}} patient · {{2}} doctor · {{3}} date · {{4}} time
#   cancel      {{1}} patient · {{2}} doctor · {{3}} date · {{4}} time
#   feedback    {{1}} review link
#
# This is the convention clinics are asked to follow (docs/runbooks/
# META_TEMPLATES.md). A clinic that orders its own differently gets a wrong-
# looking message, which is why the runbook documents the order rather than
# leaving it to chance.
_ORDER: dict[str, tuple[str, ...]] = {
    "booking_confirm": ("patient", "clinic", "doctor", "on_date", "at_time"),
    "reschedule": ("patient", "doctor", "on_date", "at_time"),
    "cancel": ("patient", "doctor", "on_date", "at_time"),
    "feedback": ("review_link",),
    "location": ("clinic", "address", "maps"),
    "reminder": ("patient", "doctor", "on_date", "at_time"),
    "rating": ("clinic",),
    "leave_rebook": ("doctor", "on_date"),
}


def _values(purpose: str, **fields: str) -> list[str]:
    """Ordered parameter list for a purpose, from named fields."""
    return [str(fields.get(key) or "-") for key in _ORDER.get(purpose, ())]


async def _branch_and_plan(branch_id):
    """Branch + org plan in a SHORT-LIVED session of our own — the caller's is
    mid-booking and must not be disturbed."""
    from backend.models.schema import Branch, Organization

    async with _db_module.AsyncSessionLocal() as db:
        return (
            await db.execute(
                select(Branch, Organization.plan)
                .join(Organization, Organization.id == Branch.org_id)
                .where(Branch.id == branch_id)
            )
        ).first()


async def send_purpose(
    branch_id, to: str, purpose: str, values: list[str],
    buttons: list[dict] | None = None,
) -> bool:
    """Send the clinic's OWN approved template for `purpose`.

    The template NAME, language and parameter count come from that branch's
    WABA (wa_template_registry), not from us. Hardcoding `booking_confirm` was
    right for at most one clinic: Meta rejects an unknown name outright, so
    every other clinic's confirmations silently failed (Vinay 2026-08-04 —
    "after every call, patient should get whatsapp confirmation").

    Returns whether it was sent. RULE 4: never raises — a notification failure
    must not fail or block the booking that triggered it.
    """
    if branch_id is None or not to:
        logger.info("wa_skipped_unconfigured", reason="no_branch_or_recipient")
        return False

    try:
        from backend.services import wa_template_registry

        row = await _branch_and_plan(branch_id)
        if row is None:
            logger.warning("wa_branch_not_found", branch_id=str(branch_id))
            return False
        branch, plan = row
        if not wa_service.wa_enabled(branch, plan):
            return False

        spec = await wa_template_registry.resolve(branch, purpose)
        if spec is None:
            # A clinic that has not registered this template is not an error;
            # that notification simply does not go out.
            logger.info(
                "wa_no_template_for_purpose", purpose=purpose,
                branch_id=str(branch_id),
            )
            return False

        return await wa_service.send_template(
            branch, to, spec["name"], spec["language"],
            wa_template_registry.fit_params(values, spec["params"]),
            buttons or [], plan=plan,
        )
    except Exception as e:  # noqa: BLE001 — RULE 4
        logger.warning(
            "wa_purpose_send_failed", purpose=purpose, error=str(e)[:200]
        )
        return False


async def _queue_or_send(
    branch_id, to: str, purpose: str, values: list[str], *,
    event_key: str | None = None, buttons: list[dict] | None = None,
) -> bool:
    try:
        if event_key:
            from backend.services.wa_delivery import enqueue

            return await enqueue(
                branch_id, to, purpose, values,
                event_key=event_key, buttons=buttons,
            )
        return await send_purpose(branch_id, to, purpose, values, buttons)
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "wa_delivery_enqueue_failed", purpose=purpose, error=str(exc)[:200]
        )
        return False


class MetaService:
    """WhatsApp notification sender (real — Cloud API via wa_service)."""

    async def send_reschedule_confirmation(
        self, to: str, *, branch_id=None, clinic_name: str = "",
        doctor_name: str = "", when: str = "", token_id: str = "",
        patient_name: str = "", on_date: str = "", at_time: str = "",
    ) -> None:
        """Told the patient their appointment moved. Sent from BOTH channels:
        a reschedule agreed on the phone must land in WhatsApp too (Vinay
        2026-08-04: "all confirmations from calls should reflect in whatsapp")."""
        await _queue_or_send(
            branch_id, to, "reschedule",
            _values("reschedule", patient=patient_name, clinic=clinic_name,
                    doctor=doctor_name, on_date=on_date or when, at_time=at_time),
            event_key=(f"reschedule:{token_id}" if token_id else None),
        )

    async def send_cancellation_confirmation(
        self, to: str, *, branch_id=None, clinic_name: str = "",
        doctor_name: str = "", when: str = "", patient_name: str = "",
        on_date: str = "", at_time: str = "", token_id: str = "",
    ) -> None:
        await _queue_or_send(
            branch_id, to, "cancel",
            _values("cancel", patient=patient_name, clinic=clinic_name,
                    doctor=doctor_name, on_date=on_date or when, at_time=at_time),
            event_key=(f"cancel:{token_id}" if token_id else None),
        )

    async def send_feedback_request(
        self, to: str, *, branch_id=None, clinic_name: str = "",
        doctor_name: str = "", token_id: str = "", review_link: str = "",
        patient_name: str = "",
    ) -> None:
        await _queue_or_send(
            branch_id, to, "feedback",
            _values("feedback", patient=patient_name, clinic=clinic_name,
                    doctor=doctor_name, review_link=review_link),
            event_key=(f"feedback:{token_id}" if token_id else None),
        )

    async def send_appointment_reminder(
        self, to: str, *, branch_id=None, token_id: str = "",
        reminder_kind: str = "30m", patient_name: str = "",
        doctor_name: str = "", on_date: str = "", at_time: str = "",
    ) -> None:
        buttons = [
            {"id": f"rs:{token_id}", "title": "Reschedule"},
            {"id": f"cx:{token_id}", "title": "Cancel"},
        ] if token_id else []
        await _queue_or_send(
            branch_id, to, "reminder",
            _values(
                "reminder", patient=patient_name, doctor=doctor_name,
                on_date=on_date, at_time=at_time,
            ),
            event_key=(
                f"reminder:{reminder_kind}:{token_id}" if token_id else None
            ),
            buttons=buttons,
        )

    async def send_rating_request(
        self, to: str, *, branch_id=None, token_id: str = "",
        clinic_name: str = "",
    ) -> None:
        buttons = [
            {"id": f"rate:{token_id}:{score}", "title": f"{score} ⭐"}
            for score in (1, 2, 3, 4, 5)
        ] if token_id else []
        await _queue_or_send(
            branch_id, to, "rating",
            _values("rating", clinic=clinic_name),
            event_key=(f"rating:{token_id}" if token_id else None),
            buttons=buttons,
        )

    async def send_leave_rebook(
        self, to: str, *, branch_id=None, token_id: str = "",
        doctor_name: str = "", on_date: str = "",
    ) -> None:
        buttons = (
            [{"id": f"rs:{token_id}", "title": "Reschedule"}]
            if token_id else []
        )
        await _queue_or_send(
            branch_id, to, "leave_rebook",
            _values("leave_rebook", doctor=doctor_name, on_date=on_date),
            event_key=(f"leave-rebook:{token_id}" if token_id else None),
            buttons=buttons,
        )

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
            _template, _lang, _params, buttons = wa_templates.booking_confirm(
                clinic=clinic_name,
                doctor=doctor_name,
                booking_date=booking_date,
                appointment_time=appointment_time,
                token_number=token_number,
                address=branch.address,
                token_id=token_id or "",
                lang=wa_templates.template_lang(patient_lang),
            )
            await _queue_or_send(
                branch_id, to, "booking_confirm",
                _values(
                    "booking_confirm",
                    patient=patient_name, clinic=clinic_name,
                    doctor=doctor_name,
                    on_date=booking_date.strftime("%d %B"),
                    at_time=(
                        appointment_time.strftime("%I:%M %p").lstrip("0")
                        if appointment_time else f"token {token_number}"
                    ),
                ),
                event_key=(f"booking:{token_id}" if token_id else None),
                buttons=buttons,
            )
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
