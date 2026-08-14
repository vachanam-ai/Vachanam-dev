"""ONE-TIME wipe of all clinic/tenant data for a fresh start (Vinay, 2026-06-12).

Deletes every org and everything under it, in FK-safe order. KEEPS:
  - users with role='super_admin' (platform owners — Vinay's login)
  - alembic_version
Also flushes Redis (token counters / slot keys / rate-limit state).

Run:  python scripts/wipe_clinics.py --yes
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text  # noqa: E402

from backend.database import AsyncSessionLocal  # noqa: E402
from backend.config import settings  # noqa: E402

# Children before parents (every FK in schema.py is RESTRICT or CASCADE-safe
# in this order).
TABLES_IN_ORDER = [
    "call_logs",
    "followup_tasks",
    "calendar_write_tasks",
    "tokens",
    "calls",
    "whatsapp_sessions",
    "doctor_unavailability",
    "patients",
    "doctors",
    "billing_cycles",
    "audit_log",
]


async def main() -> None:
    if "--yes" not in sys.argv:
        print("Refusing: pass --yes to confirm full clinic-data wipe.")
        sys.exit(1)

    async with AsyncSessionLocal() as db:
        counts_before = {}
        for t in TABLES_IN_ORDER + ["users", "branches", "organizations"]:
            counts_before[t] = (await db.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()

        for t in TABLES_IN_ORDER:
            await db.execute(text(f"DELETE FROM {t}"))
        # clinic users go; platform owners stay
        await db.execute(text("DELETE FROM users WHERE role <> 'super_admin'"))
        await db.execute(text("DELETE FROM branches"))
        await db.execute(text("DELETE FROM organizations"))
        await db.commit()

        print("Wiped (rows before -> after):")
        for t in TABLES_IN_ORDER + ["users", "branches", "organizations"]:
            after = (await db.execute(text(f"SELECT count(*) FROM {t}"))).scalar_one()
            print(f"  {t:24s} {counts_before[t]:>6} -> {after}")

    # Redis: booking counters, slot keys, rate-limit state — all stale now.
    import redis.asyncio as aioredis

    r = aioredis.from_url(settings.redis_url, decode_responses=True)
    try:
        await r.flushdb()
        print("Redis flushed.")
    finally:
        await r.aclose()


if __name__ == "__main__":
    asyncio.run(main())
