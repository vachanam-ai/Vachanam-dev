"""smallest.ai Waves voice catalog + voice cloning (Vinay 2026-06-15).

TTS provider = smallest.ai. This wraps the official `smallestai` SDK for:
  - list_voices(language): the voice catalog the clinic picks from (live, proven).
  - clone_voice(display_name, file): instant voice clone → returns a voice_id.
  - delete_cloned_voice(voice_id): remove a clone.

Tenant isolation (RULE 1): we do NOT call the SDK's account-global
get_cloned_voices (it would mix every clinic's clones, and that endpoint is also
server-deprecated). Instead the cloned voice_id is stored on the owning Branch,
so each clinic only ever sees its own voice.

⚠ Cloning live-status: the installed SDK's add/delete target the `lightning-large`
model path, which the API is migrating off. clone/delete are integrated against
the official SDK method and surfaced with clear errors; verify against your
smallest.ai plan before relying on live cloning. list_voices is live-verified.
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


def list_voices(language: str | None = None) -> list[dict]:
    """Catalog of smallest.ai voices, optionally filtered to a language code
    (te/hi/ta/kn/ml/mr/bn/or). Returns [{voice_id, display_name, gender, languages}].

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
    code = (language or "").lower().strip()
    if code:
        from agent.i18n import get_lang

        target = get_lang(code).name.lower()
    out: list[dict] = []
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
    return out


# smallest.ai waves API base (POST /waves/v1/voice-cloning clones onto v3.1).
_WAVES_BASE = "https://api.smallest.ai"


def clone_voice(display_name: str, filename: str, audio_bytes: bytes, language: str = "en") -> str:
    """Instant voice clone (lightning-v3.1) from a short sample → new voice_id.

    The SDK's add_voice clones onto the RETIRED lightning-large model (410
    MODEL_DEPRECATED, and the result returns an empty WAV on v3.1). We call the
    current endpoint directly: POST /waves/v1/voice-cloning, which defaults to
    lightning-v3.1 and takes the spoken `language` so the clone matches the
    clinic's language.
    """
    if not settings.smallest_api_key:
        raise VoiceServiceError("smallest.ai is not configured (SMALLEST_API_KEY missing)")
    import httpx

    try:
        r = httpx.post(
            f"{_WAVES_BASE}/waves/v1/voice-cloning",
            headers={"Authorization": f"Bearer {settings.smallest_api_key}"},
            data={"displayName": display_name, "language": language},
            files={"file": (filename, audio_bytes, "audio/wav")},
            timeout=90.0,
        )
    except Exception as e:  # noqa: BLE001 — network/timeout
        logger.error("smallest_clone_request_failed", error=str(e)[:200])
        raise VoiceServiceError(f"Voice cloning request failed: {str(e)[:160]}")

    if r.status_code >= 400:
        logger.error("smallest_clone_failed", status=r.status_code, body=r.text[:400])
        raise VoiceServiceError(f"Voice cloning failed ({r.status_code}): {r.text[:200]}")

    body = r.json() if r.content else {}
    data = body.get("data") if isinstance(body.get("data"), dict) else {}
    voice_id = (
        body.get("voiceId") or body.get("voice_id")
        or data.get("voiceId") or data.get("voice_id")
    )
    if not voice_id:
        raise VoiceServiceError(f"Clone succeeded but no voiceId in response: {str(body)[:160]}")
    logger.info("smallest_voice_cloned", voice_id=voice_id, name=display_name[:40])
    return voice_id


def delete_cloned_voice(voice_id: str) -> None:
    """Delete a cloned voice. Best-effort — a delete failure must not block the
    clinic from clearing it locally (the caller still nulls Branch.tts_voice)."""
    try:
        _waves().delete_voice(voice_id=voice_id)
        logger.info("smallest_voice_deleted", voice_id=voice_id)
    except VoiceServiceError:
        raise
    except Exception as e:  # noqa: BLE001
        logger.warning("smallest_delete_failed", voice_id=voice_id, error=str(e)[:160])
