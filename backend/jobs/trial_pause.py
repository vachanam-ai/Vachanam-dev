"""Daily job: pause trials whose 14 days are up (CLAUDE.md — "day 14 pause if unpaid").

Registration sets organizations.trial_ends_at 14 days out. Nothing flipped the
status when that passed, so an expired-trial clinic kept getting full AI
service free, indefinitely, at ~Rs1.49/min cost to Vachanam (bug-bounty H5).

Every run: orgs with status='trial' AND trial_ends_at < now() -> status='paused'
+ admin alert. The voice agent's service gate already refuses calls for paused
orgs (and, as defense-in-depth, treats an expired trial as blocked even before
this job runs — billing_math.call_blocked).
"""
from datetime import datetime, timezone

import structlog
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.models.schema import Organization
from backend.services.admin_alert import alert_admin

logger = structlog.get_logger()


async def run_trial_pause() -> None:
    now = datetime.now(timezone.utc)
    async with _db_module.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Organization).where(
                    and_(
                        Organization.status == "trial",
                        Organization.trial_ends_at.is_not(None),
                        Organization.trial_ends_at < now,
                    )
                )
            )
        ).scalars().all()
        for org in rows:
            org.status = "paused"
            logger.info(
                "trial_paused",
                org_id=str(org.id),
                name=org.name,
                trial_ended=org.trial_ends_at.isoformat() if org.trial_ends_at else None,
            )
        if rows:
            await db.commit()
            try:
                await alert_admin("trial_expired_paused", branch_id=None)
            except Exception as e:
                logger.warning("trial_pause_alert_failed", error=str(e))
