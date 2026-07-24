"""Pre-render every branch's static Soniox opening into the shared Redis cache."""

from __future__ import annotations

import asyncio

from livekit.agents.utils import http_context
from sqlalchemy import select

from agent.i18n import get_recording_notice
from agent.livekit_minimal.agent import _voice_for_lang
from agent.livekit_minimal.greeting import (
    _greeting_cache_key,
    _greeting_cache_set,
    greeting_voice_key,
    inbound_greeting_texts,
    synth_wavs,
)
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch


async def main() -> None:
    async with AsyncSessionLocal() as db:
        branches = list((await db.execute(select(Branch))).scalars())

    async with http_context.open():
        for branch in branches:
            lang = getattr(branch, "language", None) or "te"
            clinic = (getattr(branch, "name_spoken", None) or "").strip() or branch.name
            voice = _voice_for_lang(branch, lang)
            voice_key = greeting_voice_key(voice)

            intro = inbound_greeting_texts(lang, clinic, recording_active=False)
            intro_key = _greeting_cache_key(str(branch.id), lang, voice_key, intro)
            await _greeting_cache_set(intro_key, await synth_wavs(intro, voice, lang))

            notice = get_recording_notice(lang)
            notice_key = _greeting_cache_key(
                "recording-notice", lang, voice_key, [notice]
            )
            await _greeting_cache_set(
                notice_key, await synth_wavs([notice], voice, lang)
            )
            print(f"warmed branch={branch.id} lang={lang} voice={voice_key}")


if __name__ == "__main__":
    asyncio.run(main())
