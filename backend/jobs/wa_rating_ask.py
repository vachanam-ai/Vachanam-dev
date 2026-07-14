"""Evening WhatsApp rating batch (spec 2026-07-13, WA T8).

Daily ~19:00 IST tick: every token marked ATTENDED today at a linked, gated
branch whose patient hasn't been asked and hasn't rated → one rating_ask
template (1-5 star quick replies; replies land in wa_actions.handle_rating).

Ask-once: Redis key wa:rated:{token_id} (TTL 7d) marks "asked", set BEFORE
the send — a duplicate nag is worse than a missed ask (mirror of the
pre-#152 reminder logic, deliberately inverted: ratings are nice-to-have,
reminders are not). RULE 1: per-branch scoped query. RULE 9: template carries
the clinic name only.
"""
from __future__ import annotations

import structlog
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.models.schema import Branch, Organization, Patient, Rating, Token
from backend.services import wa_service, wa_templates

logger = structlog.get_logger()

_ASKED_TTL = 7 * 24 * 3600


async def run_wa_rating_ask() -> None:
    async with _db_module.AsyncSessionLocal() as db:
        branches = (
            await db.execute(
                select(Branch, Organization.plan)
                .join(Organization, Organization.id == Branch.org_id)
                .where(Branch.wa_phone_number_id.is_not(None))
            )
        ).all()
        for branch, plan in branches:
            if not wa_service.wa_enabled(branch, plan):
                continue
            today = await _branch_today(branch)
            rows = (
                await db.execute(
                    select(Token, Patient)
                    .join(Patient, Patient.id == Token.patient_id)
                    .outerjoin(Rating, Rating.token_id == Token.id)
                    .where(
                        and_(
                            Token.branch_id == branch.id,  # RULE 1
                            Token.date == today,
                            Token.status == "attended",
                            Rating.id.is_(None),
                        )
                    )
                )
            ).all()
            for token, patient in rows:
                if not patient.phone:
                    continue
                if await _already_asked(str(token.id)):
                    continue
                template, lang, params, buttons = wa_templates.rating_ask(
                    clinic=branch.name,
                    token_id=str(token.id),
                    lang=wa_templates.template_lang(patient.preferred_language),
                )
                await wa_service.send_template(
                    branch, patient.phone, template, lang, params, buttons
                )


async def _branch_today(branch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    try:
        return datetime.now(ZoneInfo(branch.timezone or "Asia/Kolkata")).date()
    except Exception:  # noqa: BLE001
        return datetime.now().date()


async def _already_asked(token_id: str) -> bool:
    """SETNX ask-once marker; Redis trouble → treat as asked (skip) — a
    missed rating ask beats a possible nag storm."""
    try:
        from backend.redis_client import get_redis

        r = get_redis()
        return not await r.set(f"wa:rated:{token_id}", "1", nx=True, ex=_ASKED_TTL)
    except Exception as e:  # noqa: BLE001
        logger.warning("wa_rating_dedupe_unavailable", error=str(e)[:120])
        return True
