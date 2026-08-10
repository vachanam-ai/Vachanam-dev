"""Per-clinic telephony resolution (Vobiz sub-accounts, Vinay 2026-06-15).

Each clinic can have its OWN Vobiz sub-account (isolated channel pool, CDRs and
billing) instead of sharing one global account. Credentials may use the legacy
global account, but caller identity may not: every outbound dispatch must name
an outbound trunk explicitly assigned to that branch.

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
    outbound_trunk_id: str          # LiveKit outbound trunk for this clinic


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
            outbound_trunk_id=(
                getattr(branch, "outbound_trunk_id", "")
                or settings.outbound_trunk_id
                or os.getenv("OUTBOUND_TRUNK_ID", "")
            ),
        )
    # Global / shared account fallback.
    return BranchTelephony(
        subaccount_id=None,
        sip_username=settings.vobiz_auth_id,
        sip_password=settings.vobiz_auth_token,
        sip_domain="",
        outbound_trunk_id=settings.outbound_trunk_id or os.getenv("OUTBOUND_TRUNK_ID", ""),
    )


def branch_outbound_trunk_id(branch) -> str:
    """Return only the trunk explicitly assigned to this clinic.

    Never fall back to the platform trunk: doing so makes one clinic's call
    appear to come from another clinic's number.
    """
    trunk_id = str(getattr(branch, "outbound_trunk_id", "") or "").strip()
    if not trunk_id:
        logger.error(
            "outbound_blocked_missing_branch_trunk",
            branch_id=str(getattr(branch, "id", "")),
        )
        raise OutboundTrunkIsolationError(
            "branch has no explicitly assigned outbound trunk"
        )
    return trunk_id


def validate_branch_outbound_trunk(branch, supplied_trunk_id: str | None) -> str:
    """Require dispatch metadata to match the branch's stored trunk exactly."""
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
