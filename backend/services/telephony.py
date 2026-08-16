"""Telephony resolution with one shared LiveKit outbound trunk.

Caller identity is not selected by choosing a clinic-specific trunk. Every
dispatch uses the single configured ``OUTBOUND_TRUNK_ID`` and explicitly
presents the branch's database-owned DID as ``sip_number``. This removes trunk
selection as a tenant-routing input.

The SIP password is stored encrypted (Branch.vobiz_sip_password_enc); decrypt
only here, at the point of use.
"""
import os
from dataclasses import dataclass

import structlog

from backend.config import settings
from backend.services.crypto import decrypt_secret

logger = structlog.get_logger()


class OutboundTrunkIsolationError(RuntimeError):
    """Outbound dialing would not preserve the clinic's caller identity."""


@dataclass(frozen=True)
class BranchTelephony:
    subaccount_id: str | None       # None → global account (shared)
    sip_username: str
    sip_password: str               # decrypted; "" when not set
    sip_domain: str
    outbound_trunk_id: str          # the one shared LiveKit outbound trunk


def shared_outbound_trunk_id() -> str:
    """Return the sole outbound trunk or fail closed.

    Branch.outbound_trunk_id is deliberately ignored. It remains in the schema
    only so an older deployment can be rolled forward without a destructive
    migration; accepting it here would reintroduce the exact cross-clinic
    selection seam the shared-trunk design removes.
    """
    trunk_id = str(
        settings.outbound_trunk_id or os.getenv("OUTBOUND_TRUNK_ID", "") or ""
    ).strip()
    if not trunk_id:
        raise OutboundTrunkIsolationError("the shared outbound trunk is not configured")
    return trunk_id


def resolve_branch_telephony(branch) -> BranchTelephony:
    """Per-branch Vobiz creds + outbound trunk, falling back to the global
    account when the branch has no sub-account configured."""
    sub = getattr(branch, "vobiz_subaccount_id", None)
    if sub:
        try:
            pw = decrypt_secret(getattr(branch, "vobiz_sip_password_enc", "") or "")
        except ValueError:
            # A decrypt failure must not crash a job — log and fall back so the
            # call can still be attempted on the global account rather than dying.
            logger.error("branch_sip_password_decrypt_failed", branch_id=str(getattr(branch, "id", "")))
            pw = ""
        return BranchTelephony(
            subaccount_id=sub,
            sip_username=getattr(branch, "vobiz_sip_username", "") or "",
            sip_password=pw,
            sip_domain=getattr(branch, "vobiz_sip_domain", "") or "",
            outbound_trunk_id=shared_outbound_trunk_id(),
        )
    # Global / shared account fallback.
    return BranchTelephony(
        subaccount_id=None,
        sip_username=settings.vobiz_auth_id,
        sip_password=settings.vobiz_auth_token,
        sip_domain="",
        outbound_trunk_id=shared_outbound_trunk_id(),
    )


def branch_outbound_trunk_id(branch) -> str:
    """Return the one configured shared trunk.

    Caller identity no longer comes from trunk selection. The worker verifies
    this branch's DID is on the shared trunk and states that DID as
    ``sip_number`` on every dial. ``branch`` is accepted so call sites cannot
    accidentally lose their tenant context, but it does not select the trunk.
    """
    try:
        return shared_outbound_trunk_id()
    except OutboundTrunkIsolationError:
        logger.error(
            "outbound_blocked_missing_shared_trunk",
            branch_id=str(getattr(branch, "id", "")),
        )
        raise


def validate_branch_outbound_trunk(branch, supplied_trunk_id: str | None) -> str:
    """Require dispatch metadata to match the sole shared trunk exactly."""
    expected = branch_outbound_trunk_id(branch)
    supplied = str(supplied_trunk_id or "").strip()
    if supplied != expected:
        logger.error(
            "outbound_blocked_branch_trunk_mismatch",
            branch_id=str(getattr(branch, "id", "")),
        )
        raise OutboundTrunkIsolationError(
            "dispatch trunk does not match the branch outbound trunk"
        )
    return expected
