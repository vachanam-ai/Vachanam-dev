"""Per-clinic telephony resolution (Vobiz sub-accounts, Vinay 2026-06-15).

Each clinic can have its OWN Vobiz sub-account (isolated channel pool, CDRs and
billing) instead of sharing one global account. When a Branch has a sub-account
configured, these helpers return its credentials + per-clinic LiveKit outbound
trunk; otherwise they fall back to the global settings.* / env so existing
single-account branches keep working unchanged.

The SIP password is stored encrypted (Branch.vobiz_sip_password_enc); decrypt
only here, at the point of use.
"""
import os
from dataclasses import dataclass

import structlog

from backend.config import settings
from backend.services.crypto import decrypt_secret

logger = structlog.get_logger()


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
    """The LiveKit outbound trunk a clinic should dial through (per-clinic if set,
    else the global trunk). Used to stamp outbound dispatch metadata."""
    return resolve_branch_telephony(branch).outbound_trunk_id
