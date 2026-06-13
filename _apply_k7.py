import asyncio, backend.database as d
from sqlalchemy import text
async def m():
    async with d.engine.begin() as c:
        await c.execute(text("ALTER TABLE call_logs ADD COLUMN IF NOT EXISTS provider_call_id VARCHAR(128)"))
        exists = (await c.execute(text("SELECT 1 FROM pg_constraint WHERE conname='uq_call_logs_provider_call_id'"))).first()
        if not exists:
            await c.execute(text("ALTER TABLE call_logs ADD CONSTRAINT uq_call_logs_provider_call_id UNIQUE (provider_call_id)"))
        await c.execute(text("UPDATE alembic_version SET version_num='k7vobizcdr2026'"))
    print("APPLIED_OK")
asyncio.run(m())
