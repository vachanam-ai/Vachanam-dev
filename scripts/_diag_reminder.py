"""One-off diagnostic: why didn't the 4:30 reminder fire? Read-only. Last-4 only."""
import asyncio
from datetime import date, datetime
from zoneinfo import ZoneInfo
from sqlalchemy import select
from backend.database import AsyncSessionLocal
from backend.models.schema import Token, Doctor, Patient, Branch

IST = ZoneInfo("Asia/Kolkata")


async def main():
    now = datetime.now(IST)
    print("now IST:", now.strftime("%Y-%m-%d %H:%M"))
    async with AsyncSessionLocal() as db:
        rows = (await db.execute(
            select(Token, Doctor, Patient, Branch)
            .join(Doctor, Token.doctor_id == Doctor.id)
            .join(Patient, Token.patient_id == Patient.id)
            .join(Branch, Token.branch_id == Branch.id)
            .where(Token.date == now.date())
            .order_by(Token.appointment_time)
        )).all()
        print(f"tokens today: {len(rows)}")
        for t, d, p, b in rows:
            appt = t.appointment_time.strftime("%H:%M") if t.appointment_time else "None"
            created = t.created_at.astimezone(IST).strftime("%H:%M") if t.created_at else "?"
            print(f"  tok#{t.token_number} appt={appt} status={t.status} "
                  f"reminder_sent={t.reminder_sent} doc='{d.name}' "
                  f"doc_reminder={d.pre_appointment_reminder} "
                  f"phone_last4={(p.phone or '----')[-4:]} created={created} "
                  f"branch='{b.name}'")


if __name__ == "__main__":
    asyncio.run(main())
