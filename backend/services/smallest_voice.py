"""smallest.ai Waves voice catalog (Vinay 2026-06-15).

Wraps the official `smallestai` SDK for list_voices(language): the voice catalog
the clinic picks from (live, proven). Voice CLONING was REMOVED entirely
2026-07-24 (Vinay — catalog voices only); clone_voice/delete_cloned_voice and
their endpoints died with it.
"""
from __future__ import annotations

import structlog

from backend.config import settings

logger = structlog.get_logger()

# Catalog/model used for the voice list (matches the agent's lightning_v3.1 TTS).
_VOICES_MODEL = "lightning-v3.1"


class VoiceServiceError(RuntimeError):
    """Raised for any smallest.ai voice API failure (config missing or API error).
    Callers translate this to a clean HTTP error — never a 500 stack trace."""


def _waves():
    if not settings.smallest_api_key:
        raise VoiceServiceError("smallest.ai is not configured (SMALLEST_API_KEY missing)")
    from smallestai import SmallestAI

    return SmallestAI(api_key=settings.smallest_api_key).waves


def _select_top(voices: list[dict], default_id: str = "") -> list[dict]:
    """Trim the catalog to a clean 5 — 3 female + 2 male (Vinay 2026-06-21): the
    full catalog is too many options. The language's default voice is pulled to
    the front of its gender bucket so it's always offered. Genderless/short
    buckets just yield fewer. Order: females first, then males."""
    def _bucket(g: str) -> list[dict]:
        b = [v for v in voices if (v.get("gender") or "").lower() == g]
        return sorted(b, key=lambda v: v.get("voice_id") != default_id)

    return _bucket("female")[:3] + _bucket("male")[:2]


def list_voices(language: str | None = None) -> list[dict]:
    """Catalog of smallest.ai voices, optionally filtered to a language code
    (te/hi/ta/kn/ml/mr/bn). Returns up to 5 voices (3 female + 2 male) as
    [{voice_id, display_name, gender, languages}].

    smallest tags each voice with the FULL language name ("telugu", "hindi"), not
    the short code, so we translate the code → name via the i18n registry before
    matching (passing "te" directly would match nothing)."""
    try:
        resp = _waves().get_voices(model=_VOICES_MODEL)
    except VoiceServiceError:
        raise
    except Exception as e:  # noqa: BLE001 — SDK raises ApiError; normalize it
        logger.error("smallest_list_voices_failed", error=str(e)[:200])
        raise VoiceServiceError("Could not load voices from smallest.ai")

    # Short code → full language name (e.g. "te" → "telugu") to match the tags.
    target = ""
    default_id = ""
    code = (language or "").lower().strip()
    if code:
        from agent.i18n import get_lang

        lang = get_lang(code)
        target = lang.name.lower()
        default_id = lang.default_voice
    out: list[dict] = []
    # #405: blessed PRO-catalog voices (sravani) live outside the standard
    # lightning-v3.1 catalog — inject the ones matching this language so the
    # Settings picker can offer them. The agent maps them to the pro model
    # via welcome_synth.model_for_voice.
    from backend.services.welcome_synth import PRO_VOICE_INFO

    for vid, info in PRO_VOICE_INFO.items():
        if target and info["language"] != target:
            continue
        out.append(
            {
                "voice_id": vid,
                "display_name": info["display_name"],
                "gender": info["gender"],
                "languages": [info["language"]],
            }
        )
    for v in getattr(resp, "voices", None) or []:
        tags = getattr(v, "tags", None)
        langs = [str(x).lower() for x in (getattr(tags, "language", None) or [])]
        if target and target not in langs:
            continue
        out.append(
            {
                "voice_id": v.voice_id,
                "display_name": getattr(v, "display_name", None) or v.voice_id,
                "gender": getattr(tags, "gender", None),
                "languages": langs,
            }
        )
    return _select_top(out, default_id)
