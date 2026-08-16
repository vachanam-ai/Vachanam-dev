"""Fail-closed WhatsApp notification readiness checks."""
from __future__ import annotations

from backend.services import wa_service, wa_template_registry


async def purpose_readiness(branch, plan: str | None, purposes: tuple[str, ...]) -> dict:
    """Return send readiness per purpose for this exact branch and WABA.

    Connected is not enough: an entitled number, decryptable credential and
    APPROVED purpose-specific template are all required before voice fallback
    may be disabled.
    """
    if not wa_service.wa_enabled(branch, plan):
        return {purpose: False for purpose in purposes}
    mapping = await wa_template_registry.template_map(branch)
    return {purpose: purpose in mapping for purpose in purposes}
