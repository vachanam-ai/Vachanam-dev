"""One-off: fire a single outbound REMINDER call to a phone number, to prove the
instant-clip latency fix on a live call. Not wired into anything — run directly.
Uses the real clinic branch + a real active doctor; appointment time is ~now+30m.
"""
import asyncio
import json
import os
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models.schema import Branch, Doctor

PHONE = "+918096007554"
PATIENT = "Vinay"
OUT_TRUNK = os.getenv("OUTBOUND_TRUNK_ID") or "ST_iYg89UWeyHPb"
AGENT_NAME = "vachanam-agent"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        branch = (await db.execute(select(Branch).limit(1))).scalars().first()
        if branch is None:
            raise SystemExit("no Branch in DB")
        doctor = (
            await db.execute(
                select(Doctor).where(Doctor.branch_id == branch.id, Doctor.status == "active").limit(1)
            )
        ).scalars().first()
        if doctor is None:
            raise SystemExit("no active Doctor for branch")

    tz = ZoneInfo(getattr(branch, "timezone", None) or "Asia/Kolkata")
    appt = (datetime.now(tz) + timedelta(minutes=30)).strftime("%H:%M")

    meta = {
        "call_type": "reminder",
        "branch_id": str(branch.id),
        "outbound_trunk_id": OUT_TRUNK,
        "phone_number": PHONE,
        "token_id": str(uuid.uuid4()),  # proof call — no real token needed for the greeting
        "patient_name": PATIENT,
        "doctor_name": doctor.name,
        "doctor_id": str(doctor.id),
        "appointment_time": appt,
    }
    print("branch:", branch.name, "| doctor:", doctor.name, "| appt:", appt, "| trunk:", OUT_TRUNK)

    from livekit import api as lk_api

    from backend.config import settings

    lkapi = lk_api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        room = f"reminder-test-{uuid.uuid4().hex[:8]}"
        await lkapi.agent_dispatch.create_dispatch(
            lk_api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME, room=room, metadata=json.dumps(meta)
            )
        )
        print("DISPATCHED room:", room)
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    asyncio.run(main())
