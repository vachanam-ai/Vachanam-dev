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


async def run_pre_appt_reminders() -> None:
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY")):
        return  # voice control plane not configured on this deployment

    async with _db_module.AsyncSessionLocal() as db:
        branches = (await db.execute(select(Branch))).scalars().all()
        for branch in branches:
            tz = ZoneInfo(branch.timezone or "Asia/Kolkata")
            now_local = datetime.now(tz)
            lo = (now_local + timedelta(minutes=WINDOW_MIN)).time()
            hi = (now_local + timedelta(minutes=WINDOW_MAX)).time()

            rows = (
                await db.execute(
                    select(Token, Doctor, Patient)
                    .join(Doctor, Token.doctor_id == Doctor.id)
                    .join(Patient, Token.patient_id == Patient.id)
                    .where(
                        and_(
                            Token.branch_id == branch.id,  # RULE 1
                            Token.date == now_local.date(),
                            Token.status == "confirmed",
                            Token.reminder_sent.is_(False),
                            Token.appointment_time.is_not(None),
                            Token.appointment_time >= lo,
                            Token.appointment_time <= hi,
                            Doctor.booking_type == "appointment",
                            Doctor.pre_appointment_reminder.is_(True),
                        )
                    )
                )
            ).all()

            for token, doctor, patient in rows:
                if not patient.phone:
                    token.reminder_sent = True  # nothing to dial — don't rescan forever
                    continue
                token.reminder_sent = True
                await db.commit()
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
                            "phone_number": patient.phone,
                            "token_id": str(token.id),
                            "patient_name": patient.name,
                            "doctor_name": doctor.name,
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
