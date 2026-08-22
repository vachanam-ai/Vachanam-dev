"""Set one clinic's Google review URL without touching patient data."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.schema import Branch  # noqa: E402


async def set_url(clinic: str, review_url: str) -> int:
    host = (urlparse(review_url).hostname or "").lower()
    if not (
        review_url.startswith("https://")
        and (host == "g.page" or host == "maps.app.goo.gl" or host.endswith(".google.com"))
    ):
        print("Use an HTTPS Google Maps or Google review URL")
        return 1
    async with AsyncSessionLocal() as db:
        branches = (
            await db.execute(select(Branch).where(Branch.name.ilike(f"%{clinic}%")))
        ).scalars().all()
        if len(branches) != 1:
            print(f"Expected one branch, found {len(branches)}")
            return 1
        branches[0].google_review_url = review_url
        await db.commit()
    print("review URL configured")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("clinic")
    parser.add_argument("review_url")
    args = parser.parse_args()
    return asyncio.run(set_url(args.clinic, args.review_url))


if __name__ == "__main__":
    raise SystemExit(main())
