"""Fire the reminder for today's 16:30 token via the REAL reminder path."""
import asyncio
import os
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.schema import Token, Doctor, Patient, Branch
from backend.jobs.pre_appt_reminder import _dispatch_reminder_call

# LiveKitAPI() reads env, not settings — export from settings for this run.
os.environ["LIVEKIT_URL"] = settings.livekit_url
os.environ["LIVEKIT_API_KEY"] = settings.livekit_api_key
os.environ["LIVEKIT_API_SECRET"] = settings.livekit_api_secret
IST = ZoneInfo("Asia/Kolkata")


async def main():
    async with AsyncSessionLocal() as db:
        row = (await db.execute(
            select(Token, Doctor, Patient, Branch)
            .join(Doctor, Token.doctor_id == Doctor.id)
            .join(Patient, Token.patient_id == Patient.id)
            .join(Branch, Token.branch_id == Branch.id)
            .where(Token.date == datetime.now(IST).date(),
                   Token.status == "confirmed",
                   Token.appointment_time.is_not(None))
            .order_by(Token.appointment_time)
        )).first()
        if not row:
            print("no confirmed appointment token today")
            return
        t, d, p, b = row
        print(f"firing reminder: branch='{b.name}' doc='{d.name}' "
              f"appt={t.appointment_time.strftime('%H:%M')} phone_last4={(p.phone or '----')[-4:]}")
        await _dispatch_reminder_call(b, t, d, p)
        print("dispatched")


if __name__ == "__main__":
    asyncio.run(main())
