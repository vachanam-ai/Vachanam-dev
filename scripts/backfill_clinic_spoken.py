"""Backfill Branch.name_spoken — transliterate each clinic's name into its
call language's script so TTS speaks it correctly ("Datta" -> "దత్త", not
"data"). Idempotent: skips branches that already have name_spoken. Run once
after the v19 migration; the agent also lazily fills any that are still empty.
"""
import asyncio
import sys

from sqlalchemy import select

from agent.i18n.transliterate import spoken_name
from backend.database import AsyncSessionLocal
from backend.models.schema import Branch


async def main() -> None:
    async with AsyncSessionLocal() as db:
        branches = (await db.execute(select(Branch))).scalars().all()
        n = 0
        for b in branches:
            if (b.name_spoken or "").strip():
                continue
            lang = getattr(b, "language", None) or "te"
            tl = await spoken_name(b.name, lang)
            if tl and tl != b.name:
                b.name_spoken = tl
                n += 1
                print(f"  {b.name!r} -> {tl}")
        await db.commit()
        print(f"backfilled {n} of {len(branches)} branches.")


if __name__ == "__main__":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    asyncio.run(main())
