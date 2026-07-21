"""Cascade cancellation service.

Called by POST /availability/{branch_id}/{doctor_id} when an org_admin marks a
doctor unavailable for a date range. Performs, in a single DB transaction:
  a. INSERT DoctorUnavailability rows (one per date) ON CONFLICT DO NOTHING — idempotent.
  b. SELECT Token rows WHERE branch_id=X AND doctor_id=Y AND date BETWEEN from AND to
     AND status='confirmed' FOR UPDATE (lock).
  c. UPDATE each token: status='cancelled_by_clinic', cancelled_by_user_id=user_id,
     cancellation_reason=reason.
  d. INSERT FollowupTask(task_type='cascade_rebook') per cancelled token.

OUTSIDE the transaction (best-effort):
  e. For each cancelled token with google_calendar_event_id (slot-doctor): INSERT
     CalendarWriteTask(operation='delete', status='pending').

Returns dict with counts:
  unavailable_dates: int  — rows newly inserted (0 if date already existed)
  cancelled_tokens:  int  — tokens whose status was changed
  followups_scheduled: int — followup_tasks inserted

Per CLAUDE.md:
  Rule 1: every query filters by branch_id
  Rule 4: DB write first; calendar is async best-effort
  Rule 10: structlog JSON events
"""
from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Optional

import structlog
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models.schema import (
    CalendarWriteTask,
    DoctorUnavailability,
    FollowupTask,
    Token,
)

logger = structlog.get_logger()


async def cascade_for_unavailability(
    db: AsyncSession,
    branch_id: uuid.UUID,
    doctor_id: uuid.UUID,
    date_from: date,
    date_to: date,
    user_id: str,
    reason: Optional[str] = None,
    min_cancel_date: Optional[date] = None,
) -> dict:
    """Mark doctor unavailable for [date_from, date_to] and cascade-cancel existing tokens.

    B9: `min_cancel_date` (branch-local today) clamps the LOWER bound of the
    token cascade only. Unavailability rows still cover the full [from, to]
    range (harmless for past dates), but the token cancel/rebook must never
    touch PAST-dated confirmed bookings — those are patients who already came
    but were never marked attended; cancelling them corrupts show-rate
    analytics and fires "your appointment on <past date> was cancelled" rebook
    calls. When None, no clamp (backward compatible).

    Returns:
        {
            "unavailable_dates": int,   # new DoctorUnavailability rows inserted
            "cancelled_tokens":  int,   # tokens whose status flipped to cancelled_by_clinic
            "followups_scheduled": int, # FollowupTask rows inserted
        }
    """
    cancel_from = date_from
    if min_cancel_date is not None and min_cancel_date > cancel_from:
        cancel_from = min_cancel_date
    unavailable_dates_count = 0
    followups_scheduled_count = 0

    # ------------------------------------------------------------------ #
    # SINGLE TRANSACTION — steps a, b, c, d                               #
    # ------------------------------------------------------------------ #
    # Step a: INSERT DoctorUnavailability rows — one per date in [from, to].
    # ON CONFLICT (doctor_id, date) DO NOTHING makes this idempotent.

    current = date_from
    while current <= date_to:
        stmt = (
            pg_insert(DoctorUnavailability)
            .values(
                branch_id=branch_id,
                doctor_id=doctor_id,
                date=current,
                reason=reason,
                created_by_user_id=uuid.UUID(user_id) if user_id else None,
                created_at=datetime.now(timezone.utc),
            )
            .on_conflict_do_nothing(
                index_elements=None,
                constraint="uq_doctor_unavailability_doctor_date",
            )
        )
        result = await db.execute(stmt)
        # rowcount == 1 means a new row was inserted; 0 means conflict/skip
        if result.rowcount == 1:
            unavailable_dates_count += 1
        current += timedelta(days=1)

    await db.flush()

    # Step b: SELECT confirmed tokens in the date range with FOR UPDATE lock.
    # Mandatory branch_id filter — CLAUDE.md Rule 1 tripwire.
    token_result = await db.execute(
        select(Token)
        .where(
            Token.branch_id == branch_id,        # Rule 1 — mandatory
            Token.doctor_id == doctor_id,
            Token.date >= cancel_from,            # B9: never cancel past bookings
            Token.date <= date_to,
            Token.status == "confirmed",
        )
        .with_for_update()
    )
    tokens_to_cancel = list(token_result.scalars().all())

    # Capture all needed values inside session to avoid DetachedInstanceError
    # (CLAUDE.md pattern — capture before any await that could close the ORM)
    token_snapshots = [
        {
            "id": t.id,
            "branch_id": t.branch_id,
            "doctor_id": t.doctor_id,
            "patient_id": t.patient_id,
            "date": t.date,
            "appointment_time": t.appointment_time,
            "google_calendar_event_id": t.google_calendar_event_id,
        }
        for t in tokens_to_cancel
    ]

    # Steps c & d: update each token; insert FollowupTask.
    for snap in token_snapshots:
        # Step c: cancel the token
        await db.execute(
            update(Token)
            .where(
                Token.id == snap["id"],
                Token.branch_id == branch_id,      # Rule 1 — repeated for safety
            )
            .values(
                status="cancelled_by_clinic",
                cancelled_by_user_id=uuid.UUID(user_id) if user_id else None,
                cancellation_reason=reason,
            )
        )

        # Step d: insert cascade_rebook followup task
        followup = FollowupTask(
            branch_id=branch_id,
            doctor_id=snap["doctor_id"],
            patient_id=snap["patient_id"],
            token_id=snap["id"],
            task_type="cascade_rebook",
            what_to_ask=(
                f"Doctor unavailable on {snap['date'].isoformat()}. Reschedule."
            ),
            scheduled_at=datetime.now(timezone.utc) + timedelta(minutes=1),
            max_attempts=3,
            status="pending",
            channel="whatsapp",
        )
        db.add(followup)
        followups_scheduled_count += 1

    await db.commit()

    # WA T8: leave-rebook WhatsApp ping ALONGSIDE the rebook call (spec
    # 2026-07-13). Fully guarded — a WhatsApp failure never touches the
    # cascade (RULE 4/8); no-ops unless the branch is linked + plan gated.
    try:
        await _send_wa_leave_pings(db, branch_id, token_snapshots)
    except Exception as e:  # noqa: BLE001
        logger.warning("wa_leave_ping_failed", error=str(e)[:150])

    if followups_scheduled_count:
        # #299: the cascade job is parked in Redis until its cached next-due
        # time. Drop it so these fresh rebook calls go out on the next tick.
        from backend.jobs import wake_gate

        await wake_gate.clear_next_at("cascade")

    # M14: release the Redis slot keys for cancelled SLOT-doctor tokens. The
    # DB count drops to 0 but check_availability uses max(redis, db); if the
    # org_admin later REMOVES the unavailability, those slots would still read
    # "full" until each key's TTL. Token-doctor counters are NEVER decremented
    # (the counter is the queue sequence — same rule as the agent's _do_cancel).
    slot_snaps = [s for s in token_snapshots if s["appointment_time"] is not None]
    if slot_snaps:
        try:
            import redis.asyncio as _aioredis

            from backend.config import settings as _settings

            _r = _aioredis.from_url(_settings.redis_url, decode_responses=True)
            try:
                for s in slot_snaps:
                    key = (
                        f"slot:{s['doctor_id']}:{s['branch_id']}:{s['date']}:"
                        f"{s['appointment_time'].strftime('%H%M')}"
                    )
                    if int(await _r.get(key) or 0) > 0:
                        await _r.decr(key)
            finally:
                await _r.aclose()
        except Exception as exc:
            logger.warning("cascade_redis_release_failed", error=str(exc))

    cancelled_count = len(token_snapshots)

    logger.info(
        "cascade_for_unavailability_done",
        branch_id=str(branch_id),
        doctor_id=str(doctor_id),
        date_from=date_from.isoformat(),
        date_to=date_to.isoformat(),
        unavailable_dates=unavailable_dates_count,
        cancelled_tokens=cancelled_count,
        followups_scheduled=followups_scheduled_count,
    )

    # ------------------------------------------------------------------ #
    # OUTSIDE the transaction — best-effort calendar delete enqueue (step e)
    # Only for slot-doctor tokens that have a google_calendar_event_id set.
    # These run in a separate async block; failures are logged, never raised.
    # ------------------------------------------------------------------ #
    for snap in token_snapshots:
        if not snap["google_calendar_event_id"]:
            continue  # token-doctor or slot-doctor without Cal event → skip

        try:
            cal_task = CalendarWriteTask(
                branch_id=branch_id,
                token_id=snap["id"],
                operation="delete",
                payload_json={
                    "calendar_id": None,   # filled by calendar_writer from token/branch
                    "google_event_id": snap["google_calendar_event_id"],
                },
                google_event_id=snap["google_calendar_event_id"],
                status="pending",
                attempts=0,
                next_attempt_at=datetime.now(timezone.utc),
            )
            db.add(cal_task)
        except Exception as exc:
            # Best-effort — never block the main flow
            logger.warning(
                "cascade_cal_enqueue_failed",
                branch_id=str(branch_id),
                token_id=str(snap["id"]),
                error=str(exc),
            )

    try:
        await db.commit()
    except Exception as exc:
        logger.error(
            "cascade_cal_enqueue_commit_failed",
            branch_id=str(branch_id),
            error=str(exc),
        )
        # Best-effort failure — cascade itself already committed; do not re-raise.
        # But alert: these calendar-delete tasks are now lost, so the cancelled
        # appointments stay as ghost events on Google Calendar with no retry (L2).
        try:
            from backend.services.admin_alert import alert_admin

            await alert_admin("cascade_calendar_enqueue_lost", branch_id=branch_id)
        except Exception:
            pass

    return {
        "unavailable_dates": unavailable_dates_count,
        "cancelled_tokens": cancelled_count,
        "followups_scheduled": followups_scheduled_count,
    }


async def _send_wa_leave_pings(
    db: AsyncSession, branch_id: uuid.UUID, token_snapshots: list[dict]
) -> None:
    """WA T8: one leave_rebook template per cascade-cancelled token, alongside
    the rebook call. Caller wraps in try/except (RULE 4); wa_enabled gates
    creds/link/plan, so this is a no-op until WhatsApp is live for the branch."""
    if not token_snapshots:
        return
    from backend.models.schema import Branch, Doctor, Organization, Patient
    from backend.services import wa_service, wa_templates

    row = (
        await db.execute(
            select(Branch, Organization.plan)
            .join(Organization, Organization.id == Branch.org_id)
            .where(Branch.id == branch_id)
        )
    ).first()
    if row is None:
        return
    branch, plan = row
    if not wa_service.wa_enabled(branch, plan):
        return
    doctor = (
        await db.execute(
            select(Doctor).where(Doctor.id == token_snapshots[0]["doctor_id"])
        )
    ).scalar_one_or_none()
    for snap in token_snapshots:
        patient = (
            await db.execute(select(Patient).where(Patient.id == snap["patient_id"]))
        ).scalar_one_or_none()
        if patient is None or not patient.phone:
            continue
        template, lang, params, buttons = wa_templates.leave_rebook(
            doctor=doctor.name if doctor else "the doctor",
            on_date=snap["date"],
            token_id=str(snap["id"]),
            lang=wa_templates.template_lang(patient.preferred_language),
        )
        await wa_service.send_template(
            branch, patient.phone, template, lang, params, buttons, plan=plan
        )
