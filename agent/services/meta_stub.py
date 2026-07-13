"""WhatsApp service for the voice agent — delegates to the REAL backend
implementation as of WA T4 (spec 2026-07-13). The module keeps its historical
name/import path so agent code is untouched; the backend service carries the
no-op behavior when WhatsApp isn't configured (no creds / unlinked branch /
ungated plan), so dev calls still never block on WhatsApp delivery."""
from backend.services.meta_service import MetaService

__all__ = ["MetaService"]
