"""Tenant-safe Soniox voice-cloning gateway.

The Soniox project inventory is global to our API key.  Routes must only expose
BranchVoice rows and use this module to reconcile those rows with Soniox; a raw
provider list is never returned to a clinic.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

from backend.config import settings

logger = structlog.get_logger()
MAX_CLIP_BYTES = 10 * 1024 * 1024
CUSTOM_VOICE_CLINIC_SLOTS = 10
CONSENT_TEXT = (
    "I confirm that the speaker owns this voice or gave explicit permission "
    "for this clinic to create and use an AI voice clone."
)


@dataclass(slots=True)
class SonioxVoiceError(Exception):
    status_code: int
    error_type: str
    message: str
    request_id: str | None = None


def _headers() -> dict[str, str]:
    if not settings.soniox_jp_api_key:
        raise SonioxVoiceError(503, "not_configured", "Voice cloning is not configured")
    return {"Authorization": f"Bearer {settings.soniox_jp_api_key}"}


def _provider_error(response: httpx.Response) -> SonioxVoiceError:
    try:
        body = response.json()
    except ValueError:
        body = {}
    error_type = str(body.get("error_type") or "provider_error")[:64]
    message = str(body.get("message") or "Soniox could not complete the request")[:300]
    request_id = body.get("request_id") or response.headers.get("x-request-id")
    status = response.status_code if 400 <= response.status_code < 600 else 502
    return SonioxVoiceError(status, error_type, message, request_id)


async def list_provider_voices() -> list[dict]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            response = await client.get(
                f"{settings.soniox_jp_api_url.rstrip('/')}/voices",
                headers=_headers(),
                params={"limit": 1000},
            )
    except httpx.HTTPError as exc:
        raise SonioxVoiceError(502, "provider_unavailable", "Soniox is temporarily unavailable") from exc
    if response.status_code != 200:
        raise _provider_error(response)
    return list(response.json().get("voices") or [])


async def create_provider_voice(
    *, provider_name: str, filename: str, content_type: str, audio: bytes
) -> dict:
    safe_filename = Path(filename).name[:255] or "voice-sample.webm"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5)) as client:
            response = await client.post(
                f"{settings.soniox_jp_api_url.rstrip('/')}/voices",
                headers=_headers(),
                data={"name": provider_name},
                files={"file": (safe_filename, audio, content_type)},
            )
    except httpx.HTTPError as exc:
        raise SonioxVoiceError(502, "provider_unavailable", "Soniox is temporarily unavailable") from exc
    if response.status_code != 201:
        raise _provider_error(response)
    return response.json()


async def delete_provider_voice(provider_voice_id: str) -> None:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15, connect=5)) as client:
            response = await client.delete(
                f"{settings.soniox_jp_api_url.rstrip('/')}/voices/{provider_voice_id}",
                headers=_headers(),
            )
    except httpx.HTTPError as exc:
        raise SonioxVoiceError(502, "provider_unavailable", "Soniox is temporarily unavailable") from exc
    if response.status_code not in {204, 404}:
        raise _provider_error(response)


async def preview_voice(*, provider_voice_id: str, language: str, text: str) -> tuple[bytes, str]:
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30, connect=5)) as client:
            response = await client.post(
                settings.soniox_jp_tts_http_url,
                headers={**_headers(), "Content-Type": "application/json"},
                json={
                    "model": settings.soniox_tts_model,
                    "language": language,
                    "voice": provider_voice_id,
                    "audio_format": "mp3",
                    "text": text,
                },
            )
    except httpx.HTTPError as exc:
        raise SonioxVoiceError(502, "provider_unavailable", "Soniox is temporarily unavailable") from exc
    if response.status_code != 200:
        raise _provider_error(response)
    return response.content, response.headers.get("content-type", "audio/mpeg")


def model_state(voice: dict) -> tuple[str, str | None, str | None]:
    models = list(voice.get("models") or [])
    state = next(
        (item for item in models if item.get("model") == settings.soniox_tts_model),
        models[0] if models else {},
    )
    return (
        str(state.get("status") or "processing"),
        state.get("error_type"),
        state.get("error_message"),
    )
