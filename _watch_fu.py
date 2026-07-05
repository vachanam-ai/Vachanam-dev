import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from backend.config import settings
async def check():
    eng = create_async_engine(settings.database_url)
    async with eng.connect() as c:
        r = (await c.execute(text(
            "SELECT status, attempt_count, updated_at::timestamp(0) FROM followup_tasks WHERE task_type='doctor_advice' ORDER BY created_at DESC LIMIT 1"))).first()
    await eng.dispose()
    return r
async def main():
    for i in range(12):  # up to ~18 min
        r = await check()
        print(f"[{time.strftime('%H:%M:%S')}] status={r[0]} attempts={r[1]} updated={r[2]}", flush=True)
        if r[0] != "pending":
            print("DISPATCHED/RESOLVED"); return
        await asyncio.sleep(90)
    print("STILL PENDING after watch window")
asyncio.run(main())
