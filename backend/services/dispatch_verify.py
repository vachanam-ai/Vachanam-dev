"""#423: shared join-verification for every outbound agent dispatch.

create_dispatch succeeds even when NO worker is registered with LiveKit (a
bad deploy leaves the agent process up but unconnected), so 'dispatch
created' used to mark work done while the room sat empty and the patient
never got the call — three real follow-ups lost 2026-07-19/20. Every
outbound job (follow-up, reminder, cascade-rebook) now confirms an agent
participant actually joined before counting the call as placed; unclaimed
rooms are deleted and the job's own retry logic re-attempts next tick.
"""
from __future__ import annotations

import asyncio

import structlog

logger = structlog.get_logger()

JOIN_TIMEOUT_S = 30.0  # worst post-deploy registration ~90s; healthy join ~1-3s
JOIN_POLL_S = 3.0


async def agent_joined(lkapi, room: str) -> bool:
    """True once an agent participant is in `room`; False on timeout. Poll
    errors are logged and treated as 'not joined yet' — never raised."""
    from livekit import api as lk_api

    waited = 0.0
    while waited <= JOIN_TIMEOUT_S:
        try:
            parts = await lkapi.room.list_participants(
                lk_api.ListParticipantsRequest(room=room))
            for p in parts.participants:
                if p.identity.startswith("agent-"):
                    return True
        except Exception as e:  # noqa: BLE001
            logger.warning("dispatch_join_poll_failed", room=room, error=str(e)[:120])
        await asyncio.sleep(JOIN_POLL_S)
        waited += JOIN_POLL_S
    return False


async def verify_or_cleanup(lkapi, room: str, context: str) -> bool:
    """agent_joined + best-effort empty-room cleanup + loud log on loss."""
    from livekit import api as lk_api

    if await agent_joined(lkapi, room):
        return True
    logger.error("dispatch_unclaimed", room=room, context=context,
                 waited_s=JOIN_TIMEOUT_S)
    try:
        await lkapi.room.delete_room(lk_api.DeleteRoomRequest(room=room))
    except Exception:  # noqa: BLE001
        pass
    return False
