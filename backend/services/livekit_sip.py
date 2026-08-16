"""LiveKit SIP trunk wiring — keeps the inbound trunk's number list in sync
with branches.did_number so a saved DID starts routing calls immediately.

Reads LIVEKIT_URL / LIVEKIT_API_KEY / LIVEKIT_API_SECRET / INBOUND_TRUNK_ID
from the environment. All failures are reported, never raised — saving a DID
in settings must not 500 because the telephony control plane hiccuped.
"""
import os
from contextlib import asynccontextmanager

import structlog
from dotenv import load_dotenv

# pydantic-settings reads .env into the Settings object only — the LiveKit SDK
# and this module need real environment variables.
load_dotenv()

logger = structlog.get_logger()


def _inbound_trunk_id() -> str:
    return str(os.getenv("INBOUND_TRUNK_ID") or "").strip()


def _outbound_trunk_id() -> str:
    from backend.config import settings

    return str(settings.outbound_trunk_id or os.getenv("OUTBOUND_TRUNK_ID") or "").strip()


@asynccontextmanager
async def _trunk_write_lock(trunk_id: str):
    """Serialize LiveKit's read-modify-write number updates across replicas.

    LiveKit replaces the entire ``numbers`` list. Without a distributed lock,
    two clinics onboarded together can each read the same old list and the last
    writer silently removes the other clinic. A transaction-scoped PostgreSQL
    advisory lock uses infrastructure we already require and releases itself on
    every exception/process death.
    """
    from sqlalchemy import text

    from backend.database import AsyncSessionLocal

    async with AsyncSessionLocal() as db:
        async with db.begin():
            await db.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
                {"key": f"livekit-trunk:{trunk_id}"},
            )
            yield


async def sync_did_to_inbound_trunk(did_number: str) -> dict:
    """Ensure ``did_number`` is in the LiveKit inbound trunk's accepted numbers.

    Returns {"ok": bool, "detail": str}. Idempotent.
    """
    trunk_id = _inbound_trunk_id()
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and trunk_id):
        return {"ok": False, "detail": "LiveKit credentials not configured on this server"}

    try:
        from livekit import api as lk_api

        async with _trunk_write_lock(trunk_id):
            lkapi = lk_api.LiveKitAPI()
            try:
                trunks = await lkapi.sip.list_inbound_trunk(
                    lk_api.ListSIPInboundTrunkRequest(trunk_ids=[trunk_id])
                )
                if not trunks.items:
                    return {"ok": False, "detail": f"Inbound trunk {trunk_id} not found"}
                trunk = trunks.items[0]
                numbers = list(trunk.numbers)
                if did_number in numbers:
                    return {"ok": True, "detail": "already wired"}

                numbers.append(did_number)
                await lkapi.sip.update_inbound_trunk_fields(
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
    trunk_id = _inbound_trunk_id()
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and trunk_id):
        return {"ok": False, "detail": "LiveKit credentials not configured on this server"}

    try:
        from livekit import api as lk_api

        async with _trunk_write_lock(trunk_id):
            lkapi = lk_api.LiveKitAPI()
            try:
                trunks = await lkapi.sip.list_inbound_trunk(
                    lk_api.ListSIPInboundTrunkRequest(trunk_ids=[trunk_id])
                )
                if not trunks.items:
                    return {"ok": False, "detail": f"Inbound trunk {trunk_id} not found"}
                numbers = list(trunks.items[0].numbers)
                if did_number not in numbers:
                    return {"ok": True, "detail": "already absent"}
                numbers = [n for n in numbers if n != did_number]
                await lkapi.sip.update_inbound_trunk_fields(
                    trunk_id=trunk_id, numbers=numbers
                )
                logger.info("did_unwired_from_trunk", did=did_number[-4:], trunk_id=trunk_id)
                return {"ok": True, "detail": "removed"}
            finally:
                await lkapi.aclose()
    except Exception as e:
        logger.error("did_trunk_remove_failed", did=did_number[-4:], error=str(e))
        return {"ok": False, "detail": str(e)[:200]}


async def sync_did_to_outbound_trunk(did_number: str) -> dict:
    """Add one clinic DID to the shared outbound trunk's allowed identities."""
    trunk_id = _outbound_trunk_id()
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and trunk_id):
        return {"ok": False, "detail": "Shared outbound trunk is not configured"}
    try:
        from livekit import api as lk_api

        async with _trunk_write_lock(trunk_id):
            lkapi = lk_api.LiveKitAPI()
            try:
                result = await lkapi.sip.list_outbound_trunk(
                    lk_api.ListSIPOutboundTrunkRequest(trunk_ids=[trunk_id])
                )
                if not result.items:
                    return {"ok": False, "detail": f"Outbound trunk {trunk_id} not found"}
                numbers = list(result.items[0].numbers)
                if did_number in numbers:
                    return {"ok": True, "detail": "already wired"}
                await lkapi.sip.update_outbound_trunk_fields(
                    trunk_id=trunk_id, numbers=[*numbers, did_number]
                )
                logger.info("did_wired_to_outbound_trunk", did=did_number[-4:], total=len(numbers) + 1)
                return {"ok": True, "detail": "wired"}
            finally:
                await lkapi.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.error("did_outbound_trunk_sync_failed", did=did_number[-4:], error=str(exc))
        return {"ok": False, "detail": str(exc)[:200]}


async def remove_did_from_outbound_trunk(did_number: str) -> dict:
    """Remove an old/deleted clinic identity from the shared outbound trunk."""
    trunk_id = _outbound_trunk_id()
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY") and trunk_id):
        return {"ok": False, "detail": "Shared outbound trunk is not configured"}
    try:
        from livekit import api as lk_api

        async with _trunk_write_lock(trunk_id):
            lkapi = lk_api.LiveKitAPI()
            try:
                result = await lkapi.sip.list_outbound_trunk(
                    lk_api.ListSIPOutboundTrunkRequest(trunk_ids=[trunk_id])
                )
                if not result.items:
                    return {"ok": False, "detail": f"Outbound trunk {trunk_id} not found"}
                numbers = list(result.items[0].numbers)
                if did_number not in numbers:
                    return {"ok": True, "detail": "already absent"}
                await lkapi.sip.update_outbound_trunk_fields(
                    trunk_id=trunk_id, numbers=[number for number in numbers if number != did_number]
                )
                logger.info("did_unwired_from_outbound_trunk", did=did_number[-4:])
                return {"ok": True, "detail": "removed"}
            finally:
                await lkapi.aclose()
    except Exception as exc:  # noqa: BLE001
        logger.error("did_outbound_trunk_remove_failed", did=did_number[-4:], error=str(exc))
        return {"ok": False, "detail": str(exc)[:200]}


async def reconcile_shared_trunk_numbers(did_numbers: list[str]) -> dict:
    """Make both shared trunks exactly match database-owned DIDs.

    This is the recovery path for a provider timeout after a DID save/delete.
    It is safe to run repeatedly and removes stale identities as well as adding
    missing ones.
    """
    desired = sorted({str(number).strip() for number in did_numbers if str(number).strip()})
    results: dict[str, dict] = {}
    specs = (
        ("inbound", _inbound_trunk_id(), "list_inbound_trunk", "update_inbound_trunk_fields"),
        ("outbound", _outbound_trunk_id(), "list_outbound_trunk", "update_outbound_trunk_fields"),
    )
    if not (os.getenv("LIVEKIT_URL") and os.getenv("LIVEKIT_API_KEY")):
        return {name: {"ok": False, "detail": "LiveKit credentials not configured"} for name, *_ in specs}

    from livekit import api as lk_api

    for name, trunk_id, list_method, update_method in specs:
        if not trunk_id:
            results[name] = {"ok": False, "detail": f"Shared {name} trunk is not configured"}
            continue
        try:
            async with _trunk_write_lock(trunk_id):
                lkapi = lk_api.LiveKitAPI()
                try:
                    request_cls = (
                        lk_api.ListSIPInboundTrunkRequest
                        if name == "inbound" else lk_api.ListSIPOutboundTrunkRequest
                    )
                    response = await getattr(lkapi.sip, list_method)(
                        request_cls(trunk_ids=[trunk_id])
                    )
                    if not response.items:
                        results[name] = {"ok": False, "detail": f"{name.title()} trunk not found"}
                        continue
                    current = sorted(set(response.items[0].numbers))
                    if current != desired:
                        await getattr(lkapi.sip, update_method)(
                            trunk_id=trunk_id, numbers=desired
                        )
                    results[name] = {"ok": True, "detail": "already exact" if current == desired else "reconciled"}
                finally:
                    await lkapi.aclose()
        except Exception as exc:  # noqa: BLE001
            logger.error("shared_trunk_reconcile_failed", trunk=name, error=str(exc)[:200])
            results[name] = {"ok": False, "detail": str(exc)[:200]}
    return results
