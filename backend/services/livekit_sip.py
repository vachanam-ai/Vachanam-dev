"""LiveKit SIP trunk wiring — keeps the inbound trunk's number list in sync
with branches.did_number so a saved DID starts routing calls immediately.

Reads LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET / INBOUND_TRUNK_ID
from the environment. All failures are reported, never raised — saving a DID
in settings must not 500 because the telephony control plane hiccuped.
"""
import os

import structlog
from dotenv import load_dotenv

# pydantic-settings reads .env into the Settings object only — the LiveKit SDK
# and this module need real environment variables.
load_dotenv()

logger = structlog.get_logger()


async def sync_did_to_inbound_trunk(did_number: str) -> dict:
    """Ensure ``did_number`` is in the LiveKit inbound trunk's accepted numbers.

    Returns {"ok": bool, "detail": str}. Idempotent.
    """
    trunk_id = os.getenv("INBOUND_TRUNK_ID")
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and trunk_id):
        return {"ok": False, "detail": "LiveKit credentials not configured on this server"}

    try:
        from livekit import api as lk_api

        lkapi = lk_api.LiveKitAPI()
        try:
            trunks = await lkapi.sip.list_sip_inbound_trunk(
                lk_api.ListSIPInboundTrunkRequest(trunk_ids=[trunk_id])
            )
            if not trunks.items:
                return {"ok": False, "detail": f"Inbound trunk {trunk_id} not found"}
            trunk = trunks.items[0]
            numbers = list(trunk.numbers)
            if did_number in numbers:
                return {"ok": True, "detail": "already wired"}

            numbers.append(did_number)
            await lkapi.sip.update_sip_inbound_trunk_fields(
                trunk_id=trunk_id,
                numbers=numbers,
            )
            logger.info(
                "did_wired_to_trunk", did=did_number[-4:], trunk_id=trunk_id, total=len(numbers)
            )
            return {"ok": True, "detail": "wired"}
        finally:
            await lkapi.aclose()
    except Exception as e:
        logger.error("did_trunk_sync_failed", did=did_number[-4:], error=str(e))
        return {"ok": False, "detail": str(e)[:200]}


async def remove_did_from_inbound_trunk(did_number: str) -> dict:
    """Remove ``did_number`` from the LiveKit inbound trunk's accepted numbers.

    Called when a branch changes its DID (G9): leaving the OLD number on the
    trunk means that if the number is later reassigned to a different clinic,
    inbound calls to it still hit our trunk while the DB no longer maps it — a
    latent cross-tenant routing hazard. Returns {"ok": bool, "detail": str};
    never raises. Idempotent (a number already absent is a success).
    """
    trunk_id = os.getenv("INBOUND_TRUNK_ID")
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and trunk_id):
        return {"ok": False, "detail": "LiveKit credentials not configured on this server"}

    try:
        from livekit import api as lk_api

        lkapi = lk_api.LiveKitAPI()
        try:
            trunks = await lkapi.sip.list_sip_inbound_trunk(
                lk_api.ListSIPInboundTrunkRequest(trunk_ids=[trunk_id])
            )
            if not trunks.items:
                return {"ok": False, "detail": f"Inbound trunk {trunk_id} not found"}
            numbers = list(trunks.items[0].numbers)
            if did_number not in numbers:
                return {"ok": True, "detail": "already absent"}
            numbers = [n for n in numbers if n != did_number]
            await lkapi.sip.update_sip_inbound_trunk_fields(
                trunk_id=trunk_id, numbers=numbers
            )
            logger.info("did_unwired_from_trunk", did=did_number[-4:], trunk_id=trunk_id)
            return {"ok": True, "detail": "removed"}
        finally:
            await lkapi.aclose()
    except Exception as e:
        logger.error("did_trunk_remove_failed", did=did_number[-4:], error=str(e))
        return {"ok": False, "detail": str(e)[:200]}
