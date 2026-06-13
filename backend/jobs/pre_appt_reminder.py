"""15-minute pre-appointment reminder calls (appointment-type doctors only).

Every minute: find confirmed appointment tokens whose time is 14-17 minutes
away (branch-local time), mark reminder_sent, and dispatch an outbound
LiveKit agent call with reminder context in the metadata. The agent confirms
attendance or rebooks the patient (retention) and cancels the old token.

reminder_sent is flipped BEFORE dispatch — a duplicate reminder is worse than
a missed one, and the call itself confirms with the patient anyway.
"""
import json
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import structlog
from dotenv import load_dotenv
from sqlalchemy import and_, select

import backend.database as _db_module
from backend.models.schema import Branch, Doctor, Patient, Token

load_dotenv()

logger = structlog.get_logger()

AGENT_NAME = "vachanam-agent"
WINDOW_MIN = 14
WINDOW_MAX = 17


def reminder_window(now_local: datetime) -> tuple[datetime, datetime]:
    """The [lo, hi] DATETIME window an appointment must fall in to be
    reminded now. Datetimes, not bare times: near midnight the old
    time-only comparison wrapped (lo > hi) and matched nothing, silently
    skipping late-night reminders."""
    return (
        now_local + timedelta(minutes=WINDOW_MIN),
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


async def run_pre_appt_reminders() -> None:
    from backend.config import settings as _settings

    if not _settings.voice_plane_configured:
        logger.warning("pre_appt_reminder_skipped_no_voice_plane")  # M15
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
                token.reminder_sent = True
                # commit in BOTH branches — the old no-phone path skipped the
                # commit, so phoneless tokens were rescanned every minute forever
                await db.commit()
                if not patient.phone:
                    continue  # nothing to dial
                await _dispatch_reminder_call(branch, token, doctor, patient)


async def _dispatch_reminder_call(branch: Branch, token: Token, doctor: Doctor, patient: Patient) -> None:
    """Create an explicit agent dispatch; the agent dials the patient."""
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
            logger.info(
                "reminder_call_dispatched",
                branch_id=str(branch.id),
                token_id=str(token.id),
                patient_phone=patient.phone[-4:],
                appt=token.appointment_time.strftime("%H:%M"),
            )
        finally:
            await lkapi.aclose()
    except Exception as e:
        logger.error("reminder_dispatch_failed", token_id=str(token.id), error=str(e))
