"""Offline script to generate a per-branch greeting WAV via Sarvam Bulbul TTS.

Called during Phase 9 onboarding for each new clinic. Output is stored as
`backend/static/greetings/<branch_id>.wav` and served by the agent on SIP
pickup (Component 4 of voice call flow spec — pre-cached greeting in <100ms).

Usage:
    python scripts/generate_clinic_greeting.py \\
        --branch-id <uuid> --clinic-name "ABC Hospital"
    python scripts/generate_clinic_greeting.py \\
        --branch-id <uuid> --clinic-name "ABC Hospital" --voice meera

Run from project root so the backend/ package resolves.
"""
import argparse
import asyncio
import sys
from pathlib import Path

import httpx
import structlog

# Ensure project root on path so we can import backend.config
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROJECT_ROOT))

from backend.config import settings  # noqa: E402

logger = structlog.get_logger()

# Sarvam Bulbul v3 REST endpoint for synthesis
_SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
_DEFAULT_VOICE = "meera"   # Telugu female; configurable via --voice
_DEFAULT_LANGUAGE = "te-IN"


def _greeting_text(clinic_name: str) -> str:
    """Telugu greeting played at SIP pickup. Keep short — under 4s of speech."""
    return (
        f"నమస్కారం. మీ కాల్ ని {clinic_name} కు connect చేస్తున్నాం. "
        f"కొంచెం time ఇస్తారా?"
    )


async def _synthesize(text: str, voice: str, output_path: Path) -> None:
    """Call Sarvam Bulbul TTS and write the audio to output_path.

    Sarvam returns audio as base64-encoded WAV in the JSON response.
    """
    if not settings.sarvam_api_key:
        raise RuntimeError("SARVAM_API_KEY not set in .env")

    payload = {
        "inputs": [text],
        "target_language_code": _DEFAULT_LANGUAGE,
        "speaker": voice,
        "model": "bulbul:v3",
    }
    headers = {
        "API-Subscription-Key": settings.sarvam_api_key,
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(_SARVAM_TTS_URL, json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # Sarvam returns: {"audios": ["<base64 wav>", ...]}
    audios = data.get("audios") or []
    if not audios:
        raise RuntimeError(f"Sarvam TTS returned no audio: {data}")

    import base64
    wav_bytes = base64.b64decode(audios[0])
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(wav_bytes)
    logger.info(
        "greeting_generated",
        path=str(output_path),
        bytes=len(wav_bytes),
        clinic_text_len=len(text),
    )


async def main() -> int:
    parser = argparse.ArgumentParser(description="Generate Vachanam clinic greeting WAV")
    parser.add_argument("--branch-id", required=True, help="Branch UUID (becomes filename)")
    parser.add_argument("--clinic-name", required=True, help="Clinic name to interpolate into greeting")
    parser.add_argument("--voice", default=_DEFAULT_VOICE, help=f"Sarvam voice (default: {_DEFAULT_VOICE})")
    parser.add_argument(
        "--output-dir",
        default=str(_PROJECT_ROOT / "backend" / "static" / "greetings"),
        help="Output directory for the WAV file",
    )
    args = parser.parse_args()

    text = _greeting_text(args.clinic_name)
    output_path = Path(args.output_dir) / f"{args.branch_id}.wav"

    logger.info("generating", branch_id=args.branch_id, clinic_name=args.clinic_name, voice=args.voice)
    try:
        await _synthesize(text, args.voice, output_path)
    except httpx.HTTPStatusError as e:
        logger.error("sarvam_http_error", status=e.response.status_code, body=e.response.text)
        return 1
    except Exception as e:
        logger.error("greeting_failed", error=str(e))
        return 1

    logger.info("done", output_path=str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
