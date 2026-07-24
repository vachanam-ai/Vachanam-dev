"""Regenerate landing-page language samples with the production Soniox voice."""
from __future__ import annotations

import asyncio
from pathlib import Path

from livekit.agents.utils import http_context

from agent.i18n import get_lines
from agent.livekit_minimal.greeting import synth_wavs

LANGUAGES = ("te", "hi", "ta", "kn", "ml", "mr", "bn")
OUTPUT = Path("frontend/public/voices/lang")


async def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    async with http_context.open():
        for code in LANGUAGES:
            lines = get_lines(code)
            text = lines.inbound_intro.format(clinic="Vachanam")
            wav = (await synth_wavs([text], "Priya", code))[0]
            path = OUTPUT / f"{code}.wav"
            path.write_bytes(wav)
            print(f"generated {path} ({len(wav)} bytes)")


if __name__ == "__main__":
    asyncio.run(main())
