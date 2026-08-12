"""Close out yesterday's register: a booking nobody marked is a no-show.

Vinay 2026-08-13: "patients who didn't market as attended should automatically
moved to not attended when day changes."

The receptionist PWA has both buttons (`token.attend`, `token.no_show`), but on
a busy day the no-show half simply never gets pressed — nobody walks to the
desk to report that they did not come. Nothing else in the codebase ever wrote
that status, so every unmarked booking stayed `confirmed` forever. Two costs:

  * the queue never closes — old bookings sit in `confirmed` indefinitely
  * `show_rate = attended / (attended + no_show)` had a structurally zero
    denominator term, so the dashboard reported a 100% show rate for every
    clinic, permanently. The one number that tells a clinic whether reminders
    are working was fiction.

Timezone is per BRANCH, not per server. A clinic in Asia/Kolkata rolls over at
its own midnight; using UTC would close today's afternoon register at 05:30
local. Only dates strictly BEFORE the branch's today are touched, so a booking
later today is never pre-emptively marked absent.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import structlog
from sqlalchemy import select, update

import backend.database as _db_module
from backend.models.schema import Branch, Token

logger = structlog.get_logger()

# Safety rail. A clinic that genuinely has hundreds of unmarked past bookings
# is a backfill, not a daily rollover — close what we can, log loudly, and let
# the next run continue rather than rewriting years of history in one commit.
MAX_ROWS_PER_BRANCH_PER_RUN = 500


async def run_close_past_attendance() -> None:
    """Flip `confirmed` bookings whose date is past, per branch, to `no_show`."""
    closed_total = 0
    async with _db_module.AsyncSessionLocal() as db:
        branches = (await db.execute(select(Branch))).scalars().all()
        for branch in branches:
            try:
                tz = ZoneInfo(branch.timezone or "Asia/Kolkata")
            except Exception:  # noqa: BLE001 — a bad tz string must not stop the rest
                logger.warning(
                    "attendance_close_bad_timezone",
                    branch_id=str(branch.id),
                    timezone=branch.timezone,
                )
                tz = ZoneInfo("Asia/Kolkata")
            branch_today = datetime.now(tz).date()

            # RULE 1: every read and write scoped to this branch.
            stale_ids = (
                await db.execute(
                    select(Token.id)
                    .where(
                        Token.branch_id == branch.id,
                        Token.status == "confirmed",
                        Token.date < branch_today,
                    )
                    .limit(MAX_ROWS_PER_BRANCH_PER_RUN)
                )
            ).scalars().all()
            if not stale_ids:
                continue

            await db.execute(
                update(Token)
                .where(Token.id.in_(stale_ids), Token.branch_id == branch.id)
                .values(status="no_show")
            )
            await db.commit()
            closed_total += len(stale_ids)
            logger.info(
                "attendance_auto_closed",
                branch_id=str(branch.id),
                branch_today=branch_today.isoformat(),
                closed=len(stale_ids),
                capped=len(stale_ids) == MAX_ROWS_PER_BRANCH_PER_RUN,
            )

    if closed_total:
        logger.info("attendance_close_done", closed_total=closed_total)
