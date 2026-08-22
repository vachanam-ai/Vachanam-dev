"""30-minute pre-appointment reminder calls (appointment-type doctors only).

Every minute: find confirmed appointment tokens up to 31 minutes away
(branch-local time) and dispatch outbound LiveKit agent calls with reminder
context in the metadata. The agent confirms attendance or rebooks the patient.

reminder_sent is flipped only after a worker accepts the dispatch. A failed
handoff remains pending for the next scheduler tick.
"""
import asyncio
import json
import uuid
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import structlog
from dotenv import load_dotenv
from sqlalchemy import and_, func, select, update

import backend.database as _db_module
from backend.models.schema import Branch, Doctor, Organization, Patient, Token
from backend.services import wa_templates
from backend.services.billing_math import PLANS
from backend.services.outbound_guard import lock_key
from backend.services.telephony import branch_outbound_trunk_id

load_dotenv()

logger = structlog.get_logger()

AGENT_NAME = "vachanam-agent"
# Reminder fires up to ~30 min before the appointment. RESILIENT WINDOW (Vinay
# 2026-06-22): the window spans from NOW to 31 min ahead, and fires on the FIRST
# scheduler tick inside it. The old 28-31 min band was only 3 min wide, so a
# single missed tick — a Render free-tier restart/gap, a slow job — dropped the
# reminder PERMANENTLY (reminder_sent never flipped, the band moved past the
# appointment). With lo=now, a missed 30-min mark still catches up: the patient
# just gets a slightly-later reminder (e.g. 20 min before) instead of none.
WINDOW_MAX = 31


def reminder_window(now_local: datetime) -> tuple[datetime, datetime]:
    """The [lo, hi] DATETIME window an appointment must fall in to be reminded
    now: from NOW up to WINDOW_MAX minutes ahead. lo=now (not now+28) makes the
    reminder catch up after a missed tick instead of being lost. Past
    appointments (appt < now) fall outside [lo, hi] and are correctly excluded.
    Datetimes, not bare times: near midnight a time-only compare wrapped and
    matched nothing."""
    return (
        now_local,
        now_local + timedelta(minutes=WINDOW_MAX),
    )


def appointment_in_window(
    token_date, appointment_time, lo: datetime, hi: datetime
) -> bool:
    """True when date+time (branch-local) falls inside [lo, hi]."""
    if appointment_time is None:
        return False
    appt = datetime.combine(token_date, appointment_time, tzinfo=lo.tzinfo)
    return lo <= appt <= hi


# Vinay 2026-08-07: "if appointment is booked at 5:40 for 6pm. then remainder
# call not needed. say it for 1hr. like if i book at 5 for 6 then appointment
# call not needed."
#
# Ringing someone half an hour after they arranged the appointment to tell
# them about that appointment is not a service, it is a nuisance — they were
# on the phone with us minutes ago. Inclusive at exactly one hour, which is
# the case he named.
MIN_LEAD_MINUTES = 60


def booked_too_close(created_at, token_date, appointment_time, tz) -> bool:
    """True when the booking was made within MIN_LEAD_MINUTES of its own
    appointment — i.e. there is nothing to remind them about yet.

    Eligibility is measured from when the booking was made, not only from when
    the appointment is. A missing created_at returns False so an unknown booking
    time still gets its reminder — losing a reminder is worse than one extra.
    """
    if created_at is None or appointment_time is None:
        return False
    appt = datetime.combine(token_date, appointment_time, tzinfo=tz)
    created = created_at
    if created.tzinfo is None:
        from datetime import timezone as _tz

        created = created.replace(tzinfo=_tz.utc)
    return (appt - created) <= timedelta(minutes=MIN_LEAD_MINUTES)


def _plan_has_voice(plan: str | None) -> bool:
    """False only for a plan explicitly known to buy zero voice minutes
    (`wa`). An unrecognized/None plan is treated as voice-capable — this gate
    exists to stop the `wa` plan from being dialed (no DID was ever
    provisioned for it), not to change behavior for anything else."""
    p = PLANS.get(plan)
    return p is None or p.has_voice


async def _next_due_epoch(db, branches) -> float | None:
    """UTC epoch at which the EARLIEST pending reminder becomes due, across all
    branches — or None when nothing is pending. A reminder becomes due once its
    appointment is within WINDOW_MAX minutes, so due = appointment - WINDOW_MAX.

    Used to park the job in Redis until that moment, so idle ticks never touch
    Postgres and Neon's compute can suspend (FIXLOG #299)."""
    soonest: float | None = None
    for branch in branches:
        tz = ZoneInfo(branch.timezone or "Asia/Kolkata")
        today = datetime.now(tz).date()
        row = (
            await db.execute(
                select(Token.date, Token.appointment_time)
                .join(Doctor, Token.doctor_id == Doctor.id)
                .where(
                    and_(
                        Token.branch_id == branch.id,  # RULE 1
                        Token.date >= today,
                        Token.status == "confirmed",
                        Token.reminder_sent.is_(False),
                        Token.appointment_time.is_not(None),
                        Doctor.booking_type == "appointment",
                        Doctor.pre_appointment_reminder.is_(True),
                    )
                )
                .order_by(Token.date, Token.appointment_time)
                .limit(1)
            )
        ).first()
        if not row:
            continue
        appt = datetime.combine(row[0], row[1], tzinfo=tz)
        due = (appt - timedelta(minutes=WINDOW_MAX)).timestamp()
        soonest = due if soonest is None else min(soonest, due)
    return soonest


async def run_pre_appt_reminders() -> None:
    from backend.config import settings as _settings
    from backend.jobs import wake_gate

    # #299: nothing is due yet — answer from Redis and leave Postgres asleep.
    # Fail-open: an unknown/absent key or any Redis trouble runs the DB pass.
    if not await wake_gate.should_run_scheduled("reminders"):
        return

    async with _db_module.AsyncSessionLocal() as db:
        # Loaded WITH the org's plan (WA MVP1 Task 7): `_dispatch_reminder_call`
        # must skip a `wa`-plan branch (no DID, no voice minutes — see
        # `_plan_has_voice`), while `_send_wa_reminder` still runs unconditionally
        # below (it has its own independent wa_enabled/plan gate).
        branch_rows = (
            await db.execute(
                select(Branch, Organization.plan).join(
                    Organization, Organization.id == Branch.org_id
                )
            )
        ).all()
        branches = [b for b, _ in branch_rows]
        plan_by_branch_id = {b.id: plan for b, plan in branch_rows}
        due: list[tuple[Branch, str | None, Token, Doctor, Patient, int]] = []
        for branch in branches:
            tz = ZoneInfo(branch.timezone or "Asia/Kolkata")
            now_local = datetime.now(tz)
            lo, hi = reminder_window(now_local)

            # Candidate pull is date-bounded only (covers the midnight case
            # where lo and hi are on different dates); the precise 0-31 minute
            # check happens in Python on full datetimes.
            rows = (
                await db.execute(
                    select(Token, Doctor, Patient)
                    .join(Doctor, Token.doctor_id == Doctor.id)
                    .join(Patient, Token.patient_id == Patient.id)
                    .where(
                        and_(
                            Token.branch_id == branch.id,  # RULE 1
                            Token.date.in_({lo.date(), hi.date()}),
                            Token.status == "confirmed",
                            Token.reminder_sent.is_(False),
                            Token.appointment_time.is_not(None),
                            Doctor.booking_type == "appointment",
                            Doctor.pre_appointment_reminder.is_(True),
                        )
                    )
                )
            ).all()

            for token, doctor, patient in rows:
                if not appointment_in_window(token.date, token.appointment_time, lo, hi):
                    continue
                if booked_too_close(
                    token.created_at, token.date, token.appointment_time, tz
                ):
                    # Booked within the hour — they arranged it minutes ago and
                    # already have the confirmation. Mark it so this row is not
                    # rescanned every minute until the appointment passes. This
                    # also suppresses the WhatsApp reminder below, deliberately:
                    # it would repeat the booking confirmation they just got.
                    token.reminder_sent = True
                    await db.commit()
                    logger.info(
                        "reminder_skipped_booked_within_lead",
                        branch_id=str(branch.id),
                        token_id=str(token.id),
                        lead_minutes=MIN_LEAD_MINUTES,
                    )
                    continue
                if not patient.phone:
                    # Nothing to dial — mark sent so we don't rescan it forever.
                    token.reminder_sent = True
                    await db.commit()
                    continue
                # FLIP AFTER DISPATCH (Vinay 2026-06-22: reminders went missing).
                # The old code set reminder_sent=True BEFORE dialing, so ANY
                # dispatch failure (a Render LiveKit hiccup, a transient API error)
                # permanently suppressed the reminder — reminder_sent stayed True,
                # the next tick skipped it, the patient never got the call. Now we
                # dispatch FIRST and only mark sent when create_dispatch SUCCEEDS;
                # on failure reminder_sent stays False and the next tick retries
                # (within the resilient [now, now+31] window). A rare duplicate
                # (dispatch ok but the commit below fails) is acceptable — the
                # call itself re-confirms with the patient — and far better than a
                # silently dropped reminder.
                due.append(
                    (
                        branch,
                        plan_by_branch_id.get(branch.id),
                        token,
                        doctor,
                        patient,
                        int(token.reminder_30m_dial_attempts or 0),
                    )
                )
        # One handset cannot receive two clinics at once. Process different
        # handsets concurrently, but try one handset's due reminders in order
        # until one handoff succeeds. A broken first clinic must not defer a
        # healthy sibling to another scheduler tick; one success stops the group.
        handset_groups: dict[str, list] = {}
        for item in sorted(due, key=lambda candidate: candidate[5]):
            handset = lock_key(item[4].phone)
            handset_groups.setdefault(handset, []).append(item)

        # A dispatch waits up to 30 seconds for an agent to join. Awaiting each
        # row inline made unrelated clinics queue behind one slow dispatch;
        # enough due rows turned a 17:30 reminder into 17:41. Hand every due
        # reminder to LiveKit concurrently so one clinic cannot delay another.
        # Bound this to the worker's ready-process count instead of flooding it.
        delivery_slots = asyncio.Semaphore(_settings.voice_num_idle_processes)

        async def _deliver_handset(items):
            for item in items:
                branch, plan, token, doctor, patient, _ = item
                async with delivery_slots:
                    ok = await _safe_deliver_reminder(
                        branch,
                        plan,
                        token,
                        doctor,
                        patient,
                        reminder_kind="30m",
                        voice_plane_configured=_settings.voice_plane_configured,
                    )
                if ok:
                    return item
            return None

        # Consume each handset as soon as its handoff completes. Waiting for
        # every other handset before flipping this token left a duplicate-call
        # window: a fast call could finish and release its lock while one slow
        # provider handoff kept this row visible as reminder_sent=False.
        deliveries = [
            asyncio.create_task(_deliver_handset(items))
            for items in handset_groups.values()
        ]
        try:
            for completed in asyncio.as_completed(deliveries):
                item = await completed
                if item is None:
                    continue
                branch, _, token, _, _, dial_attempts = item
                # A worker can join and get an immediate BUSY before this coroutine
                # resumes. Its retry increments dial_attempts and resets sent=False.
                # A blind ORM assignment here used to overwrite that reset and lose
                # the reminder forever. This conditional update serializes the race.
                marked = await _mark_dispatched_if_no_dial_failure(
                    db, token.id, dial_attempts
                )
                if not marked:
                    logger.info(
                        "reminder_dispatch_not_marked_after_dial_state_changed",
                        branch_id=str(branch.id),
                        token_id=str(token.id),
                    )
        finally:
            for delivery in deliveries:
                if not delivery.done():
                    delivery.cancel()
            await asyncio.gather(*deliveries, return_exceptions=True)

        # #299: park until the next reminder is genuinely due, so every tick
        # before then is a Redis read and Postgres can suspend. Capped by
        # wake_gate.SAFETY_SECONDS, so a stale value self-heals within the hour.
        await wake_gate.set_next_at("reminders", await _next_due_epoch(db, branches))


async def _safe_deliver_reminder(
    branch: Branch,
    plan: str | None,
    token: Token,
    doctor: Doctor,
    patient: Patient,
    *,
    reminder_kind: str,
    voice_plane_configured: bool,
) -> bool:
    """Isolate one clinic's delivery failure from every other due reminder."""
    try:
        return await _deliver_reminder(
            branch,
            plan,
            token,
            doctor,
            patient,
            reminder_kind=reminder_kind,
            voice_plane_configured=voice_plane_configured,
        )
    except Exception as exc:  # noqa: BLE001 - retry remains armed on False
        logger.error(
            "reminder_delivery_failed",
            branch_id=str(branch.id),
            token_id=str(token.id),
            error=str(exc)[:200],
        )
        return False


async def _mark_dispatched_if_no_dial_failure(db, token_id, expected_dial_attempts: int) -> bool:
    """Mark a joined dispatch only if its worker has not already requeued it."""
    result = await db.execute(
        update(Token)
        .where(
            Token.id == token_id,
            Token.status == "confirmed",
            Token.reminder_sent.is_(False),
            Token.reminder_30m_dial_attempts == expected_dial_attempts,
        )
        .values(
            reminder_sent=True,
            # Preserve the FIRST handoff for incident timing. Retries used to
            # overwrite 17:29 with 17:41, hiding the collision that caused them.
            reminder_30m_dispatched_at=func.coalesce(
                Token.reminder_30m_dispatched_at,
                datetime.now(timezone.utc),
            ),
        )
    )
    await db.commit()
    return bool(result.rowcount)


async def _send_wa_reminder(
    db, branch: Branch, token: Token, doctor: Doctor, patient: Patient,
    *, reminder_kind: str = "30m",
) -> bool:
    """Queue the written reminder independently from the outbound call."""
    from backend.services.meta_service import MetaService

    when = (
        token.appointment_time.strftime("%I:%M %p").lstrip("0")
        if token.appointment_time else f"token {token.token_number}"
    )
    return await MetaService().send_appointment_reminder(
        patient.phone,
        branch_id=branch.id,
        token_id=str(token.id),
        reminder_kind=reminder_kind,
        patient_name=patient.name,
        doctor_name=doctor.name,
        on_date=token.date.strftime("%d %B"),
        at_time=when,
        maps=wa_templates.maps_link(branch.address),
    )


async def _deliver_reminder(
    branch: Branch,
    plan: str | None,
    token: Token,
    doctor: Doctor,
    patient: Patient,
    *,
    reminder_kind: str,
    voice_plane_configured: bool,
) -> bool:
    """Hand the reminder to every selected channel, with a safe fallback.

    WhatsApp-only is permitted only while the approved reminder template is
    ready. If entitlement, credentials, connection or template later vanish,
    voice automatically resumes so a stale preference cannot lose reminders.
    """
    from backend.services.wa_readiness import purpose_readiness

    wa_ready = (await purpose_readiness(branch, plan, ("reminder",)))["reminder"]
    wa_accepted = await _send_wa_reminder(
        None, branch, token, doctor, patient, reminder_kind=reminder_kind
    ) if wa_ready else False

    voice_capable = _plan_has_voice(plan)
    voice_requested = voice_capable and (
        bool(getattr(branch, "reminder_calls_enabled", True)) or not wa_ready
    )
    if not voice_requested:
        return wa_accepted
    if not voice_plane_configured:
        logger.warning(
            "reminder_call_skipped_no_voice_plane",
            branch_id=str(branch.id), token_id=str(token.id),
        )
        return False
    if reminder_kind == "30m":
        return await _dispatch_reminder_call(branch, token, doctor, patient)
    return await _dispatch_reminder_call(
        branch, token, doctor, patient, reminder_kind=reminder_kind
    )


async def _dispatch_reminder_call(
    branch: Branch, token: Token, doctor: Doctor, patient: Patient, *,
    reminder_kind: str = "30m",
) -> bool:
    """Create an explicit agent dispatch; the agent dials the patient. Returns
    True only when the dispatch was created (the caller marks reminder_sent on
    True, and retries next tick on False)."""
    try:
        outbound_trunk_id = branch_outbound_trunk_id(branch)
    except RuntimeError:
        logger.error(
            "reminder_blocked_missing_branch_trunk",
            branch_id=str(branch.id),
            token_id=str(token.id),
        )
        return False
    # One outbound call per patient at a time, across every job that dials —
    # a reminder and a treatment follow-up due in the same minute rang the
    # patient twice (Vinay 2026-08-08). Returning False here leaves
    # reminder_sent unset, so the next tick retries exactly as it does for a
    # failed dispatch.
    from backend.services.outbound_guard import (
        claim_outbound_call,
        release_outbound_call,
    )

    outbound_claim = await claim_outbound_call(
        patient.phone, f"reminder_{reminder_kind}", branch.id
    )
    if not outbound_claim:
        return False
    try:
        from livekit import api as lk_api

        lkapi = lk_api.LiveKitAPI()
        try:
            room = f"reminder-{uuid.uuid4().hex[:10]}"
            await lkapi.agent_dispatch.create_dispatch(
                lk_api.CreateAgentDispatchRequest(
                    agent_name=AGENT_NAME,
                    room=room,
                    metadata=json.dumps(
                        {
                            "call_type": "reminder",
                            "reminder_kind": reminder_kind,
                            "branch_id": str(branch.id),  # outbound: no dialed DID
                            "outbound_trunk_id": outbound_trunk_id,
                            "token_id": str(token.id),
                            "outbound_lock_key": lock_key(patient.phone),
                            "outbound_lock_owner": outbound_claim,
                        }
                    ),
                )
            )
            # #423: a dispatch nobody claims (worker not registered) is a lost
            # call, not a sent reminder — verify the agent joined.
            from backend.services.dispatch_verify import verify_or_cleanup

            if not await verify_or_cleanup(lkapi, room, f"reminder:{token.id}"):
                # Nobody claimed the dispatch, so no call happened — hand the
                # number back rather than making a real retry wait out the TTL.
                await release_outbound_call(
                    patient.phone, outbound_claim, branch.id
                )
                return False
            logger.info(
                "reminder_call_dispatched",
                branch_id=str(branch.id),
                token_id=str(token.id),
                patient_phone=patient.phone[-4:],
                appt=token.appointment_time.strftime("%H:%M"),
            )
            return True
        finally:
            try:
                await lkapi.aclose()
            except Exception as close_exc:  # noqa: BLE001 - handoff truth is authoritative
                logger.warning("reminder_livekit_close_failed", error=str(close_exc)[:160])
    except Exception as e:
        logger.error("reminder_dispatch_failed", token_id=str(token.id), error=str(e))
        await release_outbound_call(patient.phone, outbound_claim, branch.id)
        return False
