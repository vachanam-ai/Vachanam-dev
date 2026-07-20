"""30-minute pre-appointment reminder calls (appointment-type doctors only).

Every minute: find confirmed appointment tokens whose time is 28-31 minutes
away (branch-local time), mark reminder_sent, and dispatch an outbound
LiveKit agent call with reminder context in the metadata. The agent confirms
attendance or rebooks the patient (retention) and cancels the old token.

reminder_sent is flipped BEFORE dispatch — a duplicate reminder is worse than
a missed one, and the call itself confirms with the patient anyway.
"""
import json
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from dotenv import load_dotenv
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.models.schema import Branch, Doctor, Patient, Token
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

    if not _settings.voice_plane_configured:
        logger.warning("pre_appt_reminder_skipped_no_voice_plane")  # M15
        return

    # #299: nothing is due yet — answer from Redis and leave Postgres asleep.
    # Fail-open: an unknown/absent key or any Redis trouble runs the DB pass.
    if not await wake_gate.should_run_scheduled("reminders"):
        return

    async with _db_module.AsyncSessionLocal() as db:
        branches = (await db.execute(select(Branch))).scalars().all()
        for branch in branches:
            tz = ZoneInfo(branch.timezone or "Asia/Kolkata")
            now_local = datetime.now(tz)
            lo, hi = reminder_window(now_local)

            # Candidate pull is date-bounded only (covers the midnight case
            # where lo and hi are on different dates); the precise 14-17min
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
                ok = await _dispatch_reminder_call(branch, token, doctor, patient)
                if ok:
                    token.reminder_sent = True
                    await db.commit()
                    # WA T8: WhatsApp reminder rides ALONGSIDE the voice call
                    # (spec 2026-07-13 — not replacing it yet). Independent
                    # guard: a WhatsApp hiccup never touches the voice path
                    # (RULE 4/8); no-ops unless branch linked + plan gated.
                    try:
                        await _send_wa_reminder(db, branch, token, doctor, patient)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("wa_reminder_failed", error=str(e)[:150])

        # #299: park until the next reminder is genuinely due, so every tick
        # before then is a Redis read and Postgres can suspend. Capped by
        # wake_gate.SAFETY_SECONDS, so a stale value self-heals within the hour.
        await wake_gate.set_next_at("reminders", await _next_due_epoch(db, branches))


async def _send_wa_reminder(db, branch: Branch, token: Token, doctor: Doctor, patient: Patient) -> None:
    """WhatsApp appt_reminder template next to the voice reminder (WA T8)."""
    from sqlalchemy import select as _select

    from backend.models.schema import Organization
    from backend.services import wa_service, wa_templates

    plan = (
        await db.execute(
            _select(Organization.plan).where(Organization.id == branch.org_id)
        )
    ).scalar_one_or_none()
    if not wa_service.wa_enabled(branch, plan):
        return
    template, lang, params, buttons = wa_templates.appt_reminder(
        doctor=doctor.name,
        appointment_time=token.appointment_time,
        token_number=token.token_number,
        token_id=str(token.id),
        lang=wa_templates.template_lang(patient.preferred_language),
    )
    await wa_service.send_template(branch, patient.phone, template, lang, params, buttons)


async def _dispatch_reminder_call(branch: Branch, token: Token, doctor: Doctor, patient: Patient) -> bool:
    """Create an explicit agent dispatch; the agent dials the patient. Returns
    True only when the dispatch was created (the caller marks reminder_sent on
    True, and retries next tick on False)."""
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
                            "branch_id": str(branch.id),  # outbound: no dialed DID
                            # Per-clinic Vobiz sub-account outbound trunk (falls
                            # back to the global trunk when not configured).
                            "outbound_trunk_id": branch_outbound_trunk_id(branch),
                            "phone_number": patient.phone,
                            "token_id": str(token.id),
                            "patient_name": patient.name,
                            "doctor_name": doctor.name,
                            "doctor_id": str(doctor.id),
                            "appointment_time": token.appointment_time.strftime("%H:%M"),
                        }
                    ),
                )
            )
            # #423: a dispatch nobody claims (worker not registered) is a lost
            # call, not a sent reminder — verify the agent joined.
            from backend.services.dispatch_verify import verify_or_cleanup

            if not await verify_or_cleanup(lkapi, room, f"reminder:{token.id}"):
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
            await lkapi.aclose()
    except Exception as e:
        logger.error("reminder_dispatch_failed", token_id=str(token.id), error=str(e))
        return False
