"""Phase-B humanizer test call: dial a number with the LIVE agent acting as a
general receptionist (NO reminder/follow-up flow), so Vinay can judge
'can a human tell?'. One-off — run directly.

Metadata carries phone_number + outbound_trunk_id + branch_id (origination) but
NO call_type, so the agent uses its default inbound-receptionist greeting/flow.
"""
import asyncio
import json
import os
import sys

from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch

PHONE = "+918096007554"
PATIENT = "Vinay"
OUT_TRUNK = os.getenv("OUTBOUND_TRUNK_ID") or "ST_iYg89UWeyHPb"
AGENT_NAME = "vachanam-agent"


async def main() -> None:
    async with AsyncSessionLocal() as db:
        branch = (await db.execute(select(Branch).limit(1))).scalars().first()
        if branch is None:
            raise SystemExit("no Branch in DB")

    meta = {
        "branch_id": str(branch.id),
        "outbound_trunk_id": OUT_TRUNK,
        "phone_number": PHONE,
        "patient_name": PATIENT,
        # NO call_type → default receptionist flow.
    }
    print(f"branch: {branch.name} | calling {PHONE[-4:]} | trunk: {OUT_TRUNK}")

    from livekit import api as lk_api

    lkapi = lk_api.LiveKitAPI(
        url=settings.livekit_url,
        api_key=settings.livekit_api_key,
        api_secret=settings.livekit_api_secret,
    )
    try:
        import uuid

        room = f"humanizer-test-{uuid.uuid4().hex[:8]}"
        await lkapi.agent_dispatch.create_dispatch(
            lk_api.CreateAgentDispatchRequest(
                agent_name=AGENT_NAME, room=room, metadata=json.dumps(meta)
            )
        )
        print("DISPATCHED room:", room)
    finally:
        await lkapi.aclose()


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
