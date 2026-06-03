# Phase 6 — Jobs + Calendar ⬜ TODO (MVP1 REDUCED SCOPE)

> **MVP1 reduced scope per client decision 2026-06-03.** WhatsApp functionality removed from MVP1 and moved to MVP2.
>
> **What stays in MVP1:**
> - Google Calendar service (create/delete booking events)
> - Token expiry job (APScheduler, every 2 minutes)
>
> **What moves to MVP2 (requires Phase 5 WhatsApp first):**
> - EOD summary job (sends WA to doctors) -- DEFERRED-MVP2
> - Follow-up calls/messages job (sends WA to patients) -- DEFERRED-MVP2
>
> **Trade-offs:** Without EOD summary, doctors check their schedule via the receptionist app or owner dashboard. Without follow-up jobs, receptionist handles follow-ups manually or via outbound voice calls.

**Goal:** Google Calendar reads/writes wired into booking flow, plus token expiry background job.

**Effort:** 1 day. **Prerequisites:** Phase 4 ✅. Google service account JSON downloaded to `./google-service-account.json`, Calendar API enabled in Google Cloud Console.

---

## Components

### 1. Google Calendar service
- [`backend/services/calendar_service.py`](../../../backend/services/calendar_service.py)
- Uses `google.oauth2.service_account.Credentials` from `GOOGLE_APPLICATION_CREDENTIALS`
- `async create_booking_event(calendar_id, patient_name, patient_phone, token_number, booking_date, appointment_time, doctor_name) -> event_id`
  - **Privacy:** stores first name only + last 4 digits of phone in summary. NEVER medical details.
  - RAISES on failure (booking must not proceed without calendar event)
  - Wraps sync google-api-client in `asyncio.to_thread`
- `async delete_event(calendar_id, event_id)` — used by `CANCEL_DAY` doctor command

### 2. Token expiry job (MVP1) + two deferred jobs (MVP2)

#### `backend/jobs/token_expiry.py` -- MVP1
- Every 2 minutes
- Finds confirmed tokens with `date < today - 1day` and marks them `no_show`
- Safety net for tokens not explicitly closed by receptionist

#### `backend/jobs/eod_summary.py` -- DEFERRED-MVP2 (requires Phase 5 WhatsApp)
- Cron: 17:30 Asia/Kolkata daily
- For each active branch → each doctor with appointments today:
  1. Auto-mark remaining `confirmed` tokens as `no_show`
  2. Build summary (attended count, no-show count, no-show patient names)
  3. Send WhatsApp to `doctor.whatsapp_number` via `MetaService` (built in Phase 5)
  4. Append prompt: "Reply with follow-up instructions if needed"

#### `backend/jobs/followup_calls.py` -- DEFERRED-MVP2 (requires Phase 5 WhatsApp)
- Cron: 09:00 Asia/Kolkata daily
- Finds `FollowupTask.scheduled_date == today AND status == 'pending'`
- For each: send WA via `MetaService`, mark `status='completed'`, `attempt_count += 1`
- On exception: `status='failed'`

### 3. Register in main.py lifespan

```python
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
import pytz
IST = pytz.timezone("Asia/Kolkata")

@asynccontextmanager
async def lifespan(app):
    scheduler = AsyncIOScheduler(timezone=IST)
    scheduler.add_job(run_token_expiry, IntervalTrigger(minutes=2))
    # MVP2 (after Phase 5 WhatsApp ships):
    # scheduler.add_job(run_eod_summary, CronTrigger(hour=17, minute=30, timezone=IST))
    # scheduler.add_job(run_followup_tasks, CronTrigger(hour=9, minute=0, timezone=IST))
    scheduler.start()
    yield
    scheduler.shutdown()
```

---

## Acceptance criteria (MVP1 — reduced)

```
[ ] Google Calendar event created when booking confirms (visible in test calendar)
[ ] Calendar event deleted when doctor cancels a day (via receptionist app or dashboard)
[ ] Manual trigger: run_token_expiry() — yesterday's confirmed tokens → no_show in DB
[ ] Server logs show scheduler_started on uvicorn boot
[ ] After uvicorn runs for 3 minutes, check logs for at least one token_expiry_job heartbeat
```

### MVP2 acceptance criteria (after Phase 5 WhatsApp ships)
```
[ ] Manual trigger: run_eod_summary() — receive WA on test doctor number with formatted summary
[ ] Manual trigger: run_followup_tasks() — patient receives WA, FollowupTask.status='completed' in DB
```

---

## Files this phase creates (MVP1)

```
backend/services/calendar_service.py
backend/jobs/token_expiry.py
```

### Files deferred to MVP2 (after Phase 5 WhatsApp)
```
backend/jobs/eod_summary.py
backend/jobs/followup_calls.py
tests/integration/test_jobs_eod.py
tests/integration/test_jobs_followup.py
```

Modifies `backend/main.py` lifespan (token_expiry job only for MVP1).
Wires `agent/tools/booking_tools.py confirm_booking` to actually call `CalendarService` (right now it accepts the service as a parameter; main.py constructs and injects it).

---

## Privacy rules (CRITICAL)

| Rule | Where |
|---|---|
| Calendar summary: `"Token #N — {first_name} (xx{phone[-4:]})"` only | `create_booking_event` |
| No medical complaint, no diagnosis, no full phone, no DOB | All calendar fields |
| WA EOD summary: aggregates only, no patient phone numbers | `eod_summary.py` |
| WA follow-up to patient: only repeats what doctor wrote in `what_to_ask`. No diagnosis. | `followup_calls.py` |

---

## What this phase does NOT do

- ❌ No billing cycle close job (that's Phase 9)
- ❌ No trial expiry job (Phase 9)
- ❌ No pre-appointment reminder (Phase 9, optional per doctor)
- ❌ No EOD summary via WhatsApp (deferred to MVP2 with Phase 5)
- ❌ No follow-up messages via WhatsApp (deferred to MVP2 with Phase 5)

Move on to [Phase 7](../07-frontend-receptionist/CLAUDE.md).
