"""Daily job: pause trials whose 14 days are up (CLAUDE.md — "day 14 pause if unpaid").

Registration sets organizations.trial_ends_at 14 days out. Nothing flipped the
status when that passed, so an expired-trial clinic kept getting full AI
service free, indefinitely, at ~Rs1.49/min cost to Vachanam (bug-bounty H5).

Every run: orgs with status='trial' AND trial_ends_at < now() -> status='paused'
+ admin alert. The voice agent's service gate already refuses calls for paused
orgs (and, as defense-in-depth, treats an expired trial as blocked even before
this job runs — billing_math.call_blocked).
"""
from datetime import date, datetime, timezone

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


async def run_trial_nudge() -> None:
    """Day-12 payment nudge (CLAUDE.md trial flow): a trial ending within 2
    days gets ONE email pointing the owner at Settings → Plan & billing to
    pay in-app. Dedup: Redis key per org, 30-day TTL (shared client, #305 —
    never build a per-call client). Worst case after a Redis wipe is one
    repeat email — acceptable. Email failure never breaks the job (RULE 8)."""
    from datetime import timedelta

    import httpx

    from backend.config import settings
    from backend.redis_client import get_redis

    if not settings.resend_api_key:
        return
    now = datetime.now(timezone.utc)
    async with _db_module.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Organization).where(
                    and_(
                        Organization.status == "trial",
                        Organization.trial_ends_at.is_not(None),
                        Organization.trial_ends_at > now,
                        Organization.trial_ends_at < now + timedelta(days=2),
                    )
                )
            )
        ).scalars().all()
    for org in rows:
        if not org.owner_email:
            continue
        try:
            if not await get_redis().set(
                f"trial_nudge:{org.id}", "1", ex=30 * 86400, nx=True
            ):
                continue  # already nudged
        except Exception:  # noqa: BLE001 — Redis down: skip, retry next run
            continue
        billing_url = f"{settings.frontend_url.rstrip('/')}/settings#plan"
        ends = org.trial_ends_at.astimezone(timezone.utc).strftime("%d %b %Y")
        try:
            async with httpx.AsyncClient(timeout=10) as c:
                r = await c.post(
                    "https://api.resend.com/emails",
                    headers={"Authorization": f"Bearer {settings.resend_api_key}"},
                    json={
                        "from": settings.resend_from,
                        "to": [org.owner_email],
                        "subject": "Your Vachanam free trial ends soon — keep your AI receptionist on",
                        "text": (
                            f"Namaste {org.name},\n\n"
                            f"Your 14-day Vachanam trial ends on {ends}. To keep your "
                            "AI receptionist answering every call, activate your plan "
                            f"here:\n\n{billing_url}\n\n"
                            "Pay securely with UPI, card or netbanking (Razorpay). "
                            "If the trial ends unpaid, your line pauses — nothing is "
                            "deleted, and paying later reactivates it instantly.\n\n"
                            "Questions? Just reply to this email.\n— Vachanam"
                        ),
                    },
                )
            if r.status_code >= 300:
                logger.error("trial_nudge_email_failed", org_id=str(org.id),
                             status=r.status_code)
            else:
                logger.info("trial_nudge_sent", org_id=str(org.id))
        except Exception as e:  # noqa: BLE001
            logger.error("trial_nudge_error", org_id=str(org.id), error=str(e)[:160])


async def run_pending_plan_changes(today: date | None = None) -> None:
    """Apply clinic-scheduled plan changes whose effective date has arrived.

    A clinic schedules a plan switch via POST /api/plan-change; it sits in
    pending_plan/pending_plan_effective until the first of the next month. This
    daily job promotes pending_plan -> plan once today >= effective, then clears
    the pending fields. Idempotent: rows with no pending change are untouched.
    """
    today = today or date.today()
    async with _db_module.AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(Organization).where(
                    and_(
                        Organization.pending_plan.is_not(None),
                        Organization.pending_plan_effective.is_not(None),
                        Organization.pending_plan_effective <= today,
                    )
                )
            )
        ).scalars().all()
        for org in rows:
            old = org.plan
            org.plan = org.pending_plan
            org.pending_plan = None
            org.pending_plan_effective = None
            logger.info(
                "pending_plan_applied", org_id=str(org.id), from_plan=old, to_plan=org.plan
            )
        if rows:
            await db.commit()
