import asyncio, sys, time
sys.stdout.reconfigure(encoding="utf-8")
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from backend.config import settings
async def main():
    eng = create_async_engine(settings.database_url)
    for i in range(15):  # ~22 min
        async with eng.connect() as c:
            t = (await c.execute(text(
                "SELECT status, attempt_count FROM followup_tasks WHERE task_type='doctor_advice' ORDER BY created_at DESC LIMIT 1"))).first()
            lk = (await c.execute(text(
                "SELECT count(*) FROM pg_locks WHERE locktype='advisory'"))).scalar()
        print(f"[{time.strftime('%H:%M:%S')}] task={t[0]}/{t[1]} advisory_locks={lk}", flush=True)
        if t[0] != "pending":
            print("TASK DISPATCHED"); break
        await asyncio.sleep(90)
    await eng.dispose()
asyncio.run(main())
