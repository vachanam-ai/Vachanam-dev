"""Pre-render each clinic's welcome+greeting to Branch.welcome_audio so the call
plays it INSTANTLY on answer (masks the ~6s session.start). Idempotent: skips
branches that already have audio unless --force. Run after the w20 migration.

Text = welcome clip ("నమస్కారం, <clinic> క్లినిక్‌కి స్వాగతం") + the approved
disclosure greeting ("నేను ఈ క్లినిక్ ఏఐ అసిస్టెంట్‌ని, చెప్పండి, మీకు నేను ఎలా సహాయం చేయగలను?")
in the clinic's voice — so it IS the full opening and the live greeting is skipped.
"""
import asyncio
import sys

from sqlalchemy import select

from agent.i18n import get_lines, get_welcome
from agent.i18n.languages import get_lang
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch
from backend.services.welcome_synth import synth_wav


def _welcome_text(clinic_spoken: str, lang_code: str) -> str:
    welcome = get_welcome(lang_code).format(clinic=clinic_spoken)
    greeting = get_lines(lang_code).disclosure_greeting.format(clinic=clinic_spoken)
    return f"{welcome} {greeting}"


async def main(force: bool) -> None:
    async with AsyncSessionLocal() as db:
        branches = (await db.execute(select(Branch))).scalars().all()
        n = 0
        for b in branches:
            need_full = not b.welcome_audio or force
            need_short = not b.welcome_short_audio or force
            if not (need_full or need_short):
                continue
            lang = getattr(b, "language", None) or "te"
            cfg = get_lang(lang)
            clinic_spoken = (b.name_spoken or "").strip() or b.name
            voice = (getattr(b, "tts_voice", None) or "").strip() or cfg.default_voice
            if need_full:
                wav = synth_wav(_welcome_text(clinic_spoken, lang), voice, cfg.tts_code)
                b.welcome_audio = wav
                print(f"  {b.name} FULL: {len(wav)} bytes (~{len(wav)/2/24000:.1f}s)")
            if need_short:
                short_text = get_welcome(lang).format(clinic=clinic_spoken)
                swav = synth_wav(short_text, voice, cfg.tts_code)
                b.welcome_short_audio = swav
                print(f"  {b.name} SHORT: {len(swav)} bytes (~{len(swav)/2/24000:.1f}s)")
            n += 1
        await db.commit()
        print(f"backfilled {n} of {len(branches)} branches.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main(force="--force" in sys.argv))
