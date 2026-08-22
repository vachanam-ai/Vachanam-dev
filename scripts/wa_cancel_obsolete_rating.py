"""Cancel obsolete rating outbox rows for one clinic without deleting history."""
from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.models.schema import Branch, WhatsAppDelivery  # noqa: E402


async def cancel(clinic: str) -> int:
    async with AsyncSessionLocal() as db:
        branches = (
            await db.execute(select(Branch).where(Branch.name.ilike(f"%{clinic}%")))
        ).scalars().all()
        if len(branches) != 1:
            print(f"Expected one branch, found {len(branches)}")
            return 1
        rows = (
            await db.execute(
                select(WhatsAppDelivery).where(
                    WhatsAppDelivery.branch_id == branches[0].id,
                    WhatsAppDelivery.purpose == "rating",
                    WhatsAppDelivery.status == "pending",
                )
            )
        ).scalars().all()
        for row in rows:
            row.status = "cancelled"
            row.last_error = "Replaced by attended-visit feedback workflow"
        await db.commit()
    print(f"cancelled {len(rows)} obsolete pending rating row(s)")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("clinic")
    return asyncio.run(cancel(parser.parse_args().clinic))


if __name__ == "__main__":
    raise SystemExit(main())
