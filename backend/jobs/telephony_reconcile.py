"""Repair shared LiveKit trunk inventories from the database source of truth."""
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models.schema import Branch
from backend.services.livekit_sip import reconcile_shared_trunk_numbers


async def run_telephony_reconcile() -> None:
    async with AsyncSessionLocal() as db:
        dids = (
            await db.execute(
                select(Branch.did_number).where(Branch.did_number.is_not(None))
            )
        ).scalars().all()
    await reconcile_shared_trunk_numbers(list(dids))
