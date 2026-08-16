"""Deterministic WhatsApp connection lifecycle.

Connection state used to be inferred differently by each caller: the settings
page trusted ``wa_status``, the connect card trusted ``wa_waba_id``, and the
send path trusted ``wa_phone_number_id``.  A partially cleared row could
therefore look disconnected in one place while still serving chats or sending
messages in another.

This module is the single authority for the two lifecycle decisions that must
never be delegated to a prompt or to frontend state:

* ``is_connected`` is true only for a branch explicitly marked connected and
  having a receiving phone-number id.
* ``disconnect_branch`` revokes the identity and removes its working-memory
  conversations in the same database transaction.  Pending deliveries are
  made terminal so reconnecting cannot resurrect an old notification.

The caller owns the commit.  That lets HTTP routes attach audit metadata and
keeps every database mutation atomic.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession


def is_connected(branch) -> bool:
    """Return the canonical, fail-closed connection state.

    ``wa_waba_id`` is intentionally not required.  Concierge/bridge accounts
    can receive and send with a phone-number id before Meta teaches us the WABA
    id through its first webhook.  Templates have their own stricter WABA gate.
    """
    return (
        getattr(branch, "wa_status", None) == "connected"
        and bool(getattr(branch, "wa_phone_number_id", None))
    )


@dataclass(frozen=True)
class DisconnectResult:
    conversations_deleted: int
    deliveries_cancelled: int


async def disconnect_branch(
    db: AsyncSession,
    branch,
    *,
    status: str = "disconnected",
) -> DisconnectResult:
    """Atomically revoke one branch's WhatsApp identity and working state."""
    from backend.models.schema import WhatsAppDelivery, WhatsAppSession

    branch_id = branch.id
    branch.wa_waba_id = None
    branch.wa_token_enc = None
    branch.wa_verified_name = None
    branch.wa_phone_number_id = None
    branch.wa_status = status
    branch.wa_connected_at = None
    branch.wa_onboarding = None
    # A disconnected clinic must never silently lose notifications because it
    # previously chose WhatsApp-only. Restore the safe voice defaults in the
    # same transaction as credential revocation.
    branch.reminder_calls_enabled = True
    branch.followup_calls_enabled = True

    purged = (
        await db.execute(
            delete(WhatsAppSession).where(WhatsAppSession.branch_id == branch_id)
        )
    ).rowcount

    # A notification that was queued under the old connection must never be
    # delivered after a later reconnect.  Sent rows remain immutable evidence;
    # only work that has not completed is made terminal.
    cancelled = (
        await db.execute(
            update(WhatsAppDelivery)
            .where(
                WhatsAppDelivery.branch_id == branch_id,
                WhatsAppDelivery.status.in_(("pending", "in_progress")),
            )
            .values(
                status="cancelled",
                last_error="branch disconnected before delivery",
            )
        )
    ).rowcount

    return DisconnectResult(
        conversations_deleted=int(purged or 0),
        deliveries_cancelled=int(cancelled or 0),
    )


async def invalidate_connection_caches(branch_id) -> None:
    """Best-effort revocation of non-authoritative WhatsApp caches."""
    from backend.services import wa_template_registry

    await wa_template_registry.invalidate(branch_id)
