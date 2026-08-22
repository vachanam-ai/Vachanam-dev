"""Evening recovery for post-visit Google feedback messages.

Daily ~19:00 IST tick: every attended token from the last two days at a linked,
gated branch with a configured Google review link gets one feedback template.

Ask-once is the durable WhatsApp outbox's unique feedback:{token_id} event key.
A provider outage is retried, while repeated job runs cannot nag the patient.
RULE 1: per-branch scoped query. RULE 9: template carries only the review URL.
"""
from __future__ import annotations

import structlog
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.models.schema import Branch, Organization, Patient, Token
from backend.services import wa_service

logger = structlog.get_logger()

async def run_wa_rating_ask() -> None:
    async with _db_module.AsyncSessionLocal() as db:
        branches = (
            await db.execute(
                select(Branch, Organization.plan)
                .join(Organization, Organization.id == Branch.org_id)
                .where(
                    Branch.wa_phone_number_id.is_not(None),
                    Branch.google_review_url.is_not(None),
                )
            )
        ).all()
        for branch, plan in branches:
            if not wa_service.wa_enabled(branch, plan):
                continue
            today = await _branch_today(branch)
            from datetime import timedelta as _td

            window_start = today - _td(days=2)  # audit #11: late attendance marking
            rows = (
                await db.execute(
                    select(Token, Patient)
                    .join(Patient, Patient.id == Token.patient_id)
                    .where(
                        and_(
                            Token.branch_id == branch.id,  # RULE 1
                            Token.date >= window_start,
                            Token.date <= today,
                            Token.status == "attended",
                        )
                    )
                )
            ).all()
            for token, patient in rows:
                if not patient.phone:
                    continue
                from backend.services.meta_service import MetaService

                await MetaService().send_feedback_request(
                    patient.phone,
                    branch_id=branch.id,
                    token_id=str(token.id),
                    clinic_name=branch.name,
                    review_link=branch.google_review_url,
                )


async def _branch_today(branch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        return datetime.now(ZoneInfo(branch.timezone or "Asia/Kolkata")).date()
    except Exception:  # noqa: BLE001
        return datetime.now().date()
