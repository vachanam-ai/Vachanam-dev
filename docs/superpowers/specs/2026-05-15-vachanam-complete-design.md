# Vachanam — Complete Design & Architecture
**Last updated:** 2026-05-15  
**Status:** Design complete, awaiting implementation  
**Founder:** Vinay Rongala, Hyderabad  

---

## ⚠️ KEY DESIGN DECISIONS — READ FIRST

These are the authoritative decisions for this project. CLAUDE.md has been updated to match all of them.

| Topic | Decision | Reason |
|---|---|---|
| LLM primary | **Gemini 2.5 Flash** | Better Telugu language performance than GPT-4o mini |
| LLM fallback | **GPT-4o mini** | Auto-fallback if Gemini fails |
| Clinic plan | **₹7,999/month, 2,100 min** | 800 min was far too low for 20 calls/day at 3.5 min each |
| Multi plan | **₹16,999/month, 4,200 min** | Same reason — covers 2 DIDs × 20 calls/day |
| Extra branch | **₹7,999/month** | Corrected from earlier ₹4,999 estimate |
| Emergency handling | **MVP: keyword detect → give emergency_contact** | No TYPE_1/TYPE_2 classification. No 108 suggestion. Simpler, avoids liability. |
| Billing cycle | **Anniversary (join date repeats monthly)** | Fairer than forcing 1st-of-month proration |

---

## 1. What Vachanam Does

Patient calls clinic number → forwarded to Vachanam AI → AI answers in Telugu → understands complaint → routes to correct doctor → checks availability → assigns token/slot atomically → confirms by voice → creates Google Calendar event → sends WhatsApp to patient and doctor.

Receptionist marks attendance on mobile PWA. Clinic owner sees analytics on dashboard. Doctor manages schedule via WhatsApp commands.

**Does NOT do:** medical advice, diagnosis, EMR, insurance, payments, video consults.

---

## 2. Tech Stack (Final)

| Layer | Tool | Notes |
|---|---|---|
| STT | Sarvam Saaras v3 | Only viable Telugu STT |
| TTS | Sarvam Bulbul v3 | Only natural Telugu TTS |
| LLM primary | **Gemini 2.5 Flash** | Better Telugu than GPT-4o mini |
| LLM fallback | **GPT-4o mini** | Auto-fallback if Gemini fails |
| Voice pipeline | LiveKit Agents 1.4.x | Self-hosted on Fly.io bom (Mumbai) |
| Telephony | Vobiz | ₹0.65/min + ₹1,000/DID/month |
| Telephony backup | Twilio | Backup SIP trunk |
| Token locking | Upstash Redis | Atomic INCR for both token + slot booking |
| Calendar | Google Calendar API v3 | Free |
| WhatsApp | Meta Cloud API v20+ | Direct, no BSP, ₹0.115/message |
| Database | Neon Postgres | Serverless, $5/month |
| ORM | SQLAlchemy 2.x async | With asyncpg |
| Migrations | Alembic | |
| Backend | FastAPI 0.110+ | Async Python |
| Scheduler | APScheduler 3.x | With Redis distributed lock |
| Agent host | Fly.io bom | Mumbai region, ₹840/month shared |
| API host | Render | $7/month Starter |
| Frontend | React 18 + Vite | PWA, offline capable |
| CSS | TailwindCSS 3.x | |
| Frontend host | Cloudflare Pages | Free |
| Payments | Razorpay | UPI + cards, subscriptions |
| Monitoring | UptimeRobot | Free, 2-min checks |
| Logging | Structlog | JSON structured always |
| Retry | Tenacity | All external API calls |

---

## 3. Pricing (Final — overrides CLAUDE.md)

### Solo — ₹1,999/month + ₹3/min
- 1 doctor, 1 DID
- **100 free minutes/month**, then ₹3/min
- 4-minute AI call cap
- Features: token booking, WhatsApp confirm, receptionist PWA, voice AI
- Billing: variable (base + overage), anniversary cycle
- Cost at 10 calls/day: ~₹2,700/month | Revenue: ₹1,999 base + overage | Margin: variable

### Clinic — ₹7,999/month flat ← MOST POPULAR
- 2–3 doctors, 1 DID
- **2,100 min included** (covers 20 calls/day × 3.5 min × 30 days)
- Overage: ₹3/min beyond 2,100
- Features: all Solo + appointment slots, follow-ups, EOD summary, analytics dashboard
- Cost at 20 calls/day: ~₹2,737/month | Margin: ~66%

### Multi — ₹16,999/month flat
- 4–6 doctors, up to 2 DIDs (2 branches)
- **4,200 min included** (20 calls/day × 2 DIDs × 3.5 min × 30)
- Overage: ₹2.50/min beyond 4,200
- Extra branch: **₹7,999/month**
- Features: all Clinic + 6 doctors, multi-branch, ambulance transfer, CSV export

### Free Trial
- 14 days, no credit card, 1,000 min limit (20 calls/day × 3.5 min × 14 days)
- Day 12: Razorpay payment link auto-sent via WhatsApp
- Day 14: service pauses if not paid

### Billing rules
- Anniversary cycle (join date repeats monthly, not 1st of month)
- No GST for now
- Razorpay subscriptions handle recurring charges
- Solo plan: Razorpay captures card upfront, bills at end of cycle
- Redis key tracks minutes: `minutes:{org_id}:{cycle_start_date}`

### Pricing P&L validation (Solo plan — confirmed viable)

Fixed cost per client: Vobiz DID ₹1,000 + infra share ~₹185 = **₹1,185/month**  
Variable cost: **₹1.49/min** | Overage revenue: **₹3.00/min** | Net per overage minute: **₹1.51**

| Usage | Min/month | Revenue | Total cost | Profit | Margin |
|---|---|---|---|---|---|
| 0 calls/day | 0 | ₹1,999 | ₹1,185 | **₹814** | 41% |
| 3 calls/day | 315 | ₹2,644 | ₹1,654 | **₹990** | 37% |
| 10 calls/day | 1,050 | ₹4,849 | ₹2,750 | **₹2,099** | 43% |
| 15 calls/day | 1,575 | ₹6,424 | ₹3,532 | **₹2,892** | 45% |

Clinic plan margins: 44–65% | Multi plan margins: 47–68%.  
**Conclusion: All three plans are profitable at every realistic usage level. Pricing unchanged.**

Natural upgrade trigger for Solo: at 20 calls/day overage = ₹6,000 → total bill = ₹7,999 (same as Clinic flat). Pitch: "You're already paying Clinic price — upgrade for appointment booking, follow-ups, and analytics."

---

## 4. Database Schema

### `organizations`
```
id, name, owner_phone, owner_email, plan (solo|clinic|multi),
subscription_started_at, razorpay_customer_id, razorpay_subscription_id,
trial_ends_at, status (active|trial|paused|cancelled), created_at
```

### `branches`
```
id, org_id (FK), name, address, city,
whatsapp_number,          ← receives patient WhatsApp messages
did_number,               ← Vobiz DID that patients call
vobiz_did_id,             ← Vobiz API ID for this DID
emergency_contact,        ← phone number shown when patient mentions emergency
google_calendar_id,       ← branch-level calendar
timezone (default: Asia/Kolkata),
status (active|inactive), created_at
```

### `doctors`
```
id, branch_id (FK), name, specialization,   ← e.g. "dentist", "general_physician"
routing_keywords,         ← text[] e.g. ["teeth","cavity","toothache"]
is_default_doctor,        ← bool: catches unmatched symptom routing
booking_type,             ← "token" | "appointment"
working_hours_start,      ← time (both types) e.g. 10:00
working_hours_end,        ← time (both types) e.g. 15:00
slot_duration_minutes,    ← int | null — appointment type only (e.g. 30)
max_concurrent_per_slot,  ← int | null — appointment type only (e.g. 3)
pre_appointment_reminder, ← bool — appointment type only (30-min outbound call)
daily_token_limit,        ← int | null — token type only
whatsapp_number,          ← doctor's personal WhatsApp for commands
google_calendar_id,       ← doctor's calendar (shared with branch calendar)
status (active|inactive), created_at
```

### `patients`
```
id, branch_id (FK), name, phone,
followup_consent,         ← bool default False — REQUIRED before any outbound call (TRAI)
created_at
```

**Note:** Phone is optional for walk-in patients. No followup calls if phone is null or followup_consent=False.

### `tokens`  
*(Used for BOTH token-type and appointment-type bookings — unified table)*
```
id, branch_id (FK), doctor_id (FK), patient_id (FK),
date,                     ← booking date
token_number,             ← sequential for token-type, null for appointment-type
appointment_time,         ← time | null — set for appointment-type
source,                   ← "voice" | "whatsapp" | "walk_in"
status,                   ← "waiting" | "attended" | "no_show" | "cancelled_by_clinic"
cancellation_reason,      ← text | null — e.g. "doctor_unavailable" (set on cancel)
call_duration_seconds,    ← voice calls only
google_calendar_event_id,
reminder_sent,            ← bool default False — prevents double reminder calls
created_at, updated_at
```

### `calls`
```
id, branch_id (FK), doctor_id (FK), token_id (FK | null),
caller_phone, direction ("inbound" | "outbound"),
call_type,                ← "inbound_booking" | "followup" | "cancellation_notify"
started_at, ended_at, duration_seconds,
livekit_room_id, vobiz_call_id,
outcome ("booked" | "no_slot" | "emergency" | "dropped" | "followup_completed"
         | "cancellation_rebooked" | "cancellation_declined" | "cancellation_unreachable")
```

### `followup_tasks`
```
id, branch_id (FK), doctor_id (FK), patient_id (FK),
requested_by_doctor_whatsapp,   ← doctor who initiated
topic,                          ← what to follow up on
specific_question,              ← exact question to ask patient
response_summary,               ← what patient said (filled after call)
attempt_count default 0,
max_attempts default 3,
status,                         ← "pending" | "in_progress" | "completed" | "unreachable"
scheduled_at,
created_at, updated_at
```

### `billing_cycles`
```
id, org_id (FK),
cycle_start, cycle_end,
plan, base_amount, included_minutes,
minutes_used, overage_minutes, overage_rate, overage_amount,
status,                    ← "open" | "invoiced" | "paid" | "failed"
razorpay_payment_id, invoice_number, created_at
```

### `whatsapp_sessions`
```
id, branch_id (FK), patient_phone,
state,                     ← "GREETING" | "WAITING_NAME" | "WAITING_DOCTOR" | "WAITING_SLOT"
                              | "CONFIRM" | "CONFIRMED" | "CANCELLATION_REBOOK"
session_data,              ← JSONB — temp booking info: {doctor_id, patient_name, complaint,
                              is_rebook, cancelled_token_id} (latter two for rebook sessions)
expires_at, created_at, updated_at
```

---

## 5. Redis Keys

```
token:{doctor_id}:{branch_id}:{date}              → atomic counter for token queue (INCR)
                                                     TTL: midnight of {date} + 2h (keys auto-expire overnight)

slot:{doctor_id}:{branch_id}:{date}:{HHMM}        → concurrent slot count (INCR, max = max_concurrent_per_slot)
                                                     TTL: slot datetime + 2h (expires after the appointment time passes)

doctor_context:{doctor_id}:{date}                  → JSON list of today's patients for EOD follow-up lookup
                                                     TTL: 36h from creation (written at booking time)

minutes:{org_id}:{cycle_start_date}               → minute counter for billing cycle (INCR per call second)
                                                     TTL: 35 days (30-day cycle + 5-day buffer for billing close)

scheduler:leader                                    → APScheduler distributed lock
                                                     TTL: 60s (NX flag — only 1 Render worker runs jobs at a time)

cancellation_session:{token_id}                    → context for outbound cancellation rebook call
                                                     {patient_name, doctor_id, branch_id, original_date, complaint}
                                                     TTL: 2h (only needed for the duration of the call window)
```

**Token booking:** `INCR token:...` → if result > daily_token_limit → `DECR` (rollback) → return "full"  
**Slot booking:** `INCR slot:...` → if result > max_concurrent_per_slot → `DECR` (rollback) → suggest next slot  
**DECR is ONLY used as rollback** — never as the primary operation.  
**TTL enforcement:** `token_expiry` job (every 2 min) handles DB cleanup; Redis keys self-expire via TTL.

---

## 6. Voice Agent Flow

```
Call arrives on Vobiz DID
  → Vobiz forwards to LiveKit SIP
  → LiveKit creates room, starts agent
  → agent.py entrypoint fires

CALL START:
  1. Fixed greeting in Telugu (no emergency check in MVP)
  2. Collect patient name
  3. Collect complaint / reason for visit

DOCTOR ROUTING (multi-doctor clinics only):
  4. Pass complaint + clinic's doctor list (names, specializations, keywords) to Gemini
  5. Gemini returns: { doctor_id, confidence: "high"|"low"|"none" }
  6. high → route silently
  7. low → ask one clarifying question
  8. none → route to is_default_doctor (general physician)
  9. Single-doctor clinic → skip routing

AVAILABILITY CHECK:
  10. Query doctor's booking_type
  Token type: ask which day → tell token queue status → assign next token
  Appointment type: ask which day → compute available ranges → patient picks time

SLOT ASSIGNMENT (atomic):
  Token: Redis INCR token:{doctor_id}:{branch_id}:{date}
  Appointment: Redis INCR slot:{doctor_id}:{branch_id}:{date}:{HHMM}
  Both: if over limit → DECR (rollback) → suggest alternative

CONFIRMATION:
  11. Collect followup_consent ("क्या हम आपको बाद में follow up call कर सकते हैं?")
  12. Read back booking details to patient
  13. Patient confirms

POST-CONFIRMATION:
  14. Google Calendar event created (MUST succeed — booking fails if calendar fails)
  15. WhatsApp confirmation to patient (fire-and-forget, never fails booking)
  16. WhatsApp notification to doctor (fire-and-forget)
  17. Structlog: booking_confirmed event

EMERGENCY (MVP — no classification):
  If patient mentions emergency keywords at ANY point:
  → "I understand this is urgent. Please note our emergency contact: {branch.emergency_contact}"
  → Continue with booking as URGENT priority token/slot
  No 108 suggestion. No TYPE_1/TYPE_2 classification in MVP.

CALL DISCONNECT:
  If token/slot was incremented but booking NOT confirmed:
  → Immediately DECR the Redis counter (token/slot rollback)
  → Log: token_released_on_disconnect

4-MINUTE CAP (Solo plan only):
  At 3:50 → AI says "We are about to wrap up"
  At 4:00 → agent calls session.disconnect() → LiveKit room closes → Vobiz hangs up
  Implementation: agent checks elapsed_seconds every tick; plan read from branch JWT/DB at call start

SESSION STATE (session_state.py dataclass):
  call_type: "inbound_booking" | "followup" | "cancellation_notify"
  branch_id, doctor_id, patient_name, complaint
  token_held: bool, token_confirmed: bool, token_redis_key: str
  followup_consent: bool
  is_rebook: bool, cancelled_token_id: uuid | None   ← for cancellation rebook calls
  elapsed_seconds: int                                ← for Solo plan 4-min cap
```

---

## 7. Availability Range Algorithm (Appointment Type)

```python
async def compute_available_ranges(doctor, branch_id, date, query_start=None, query_end=None):
    slots = generate_time_slots(
        doctor.working_hours_start,
        doctor.working_hours_end,
        doctor.slot_duration_minutes
    )
    if query_start and query_end:
        slots = [s for s in slots if query_start <= s < query_end]

    available = []
    for slot in slots:
        booked = int(await redis.get(f"slot:{doctor.id}:{branch_id}:{date}:{slot:%H%M}") or 0)
        if booked < doctor.max_concurrent_per_slot:
            available.append(slot)

    # Merge consecutive slots into ranges
    ranges = []
    if not available:
        return []
    start = prev = available[0]
    duration = timedelta(minutes=doctor.slot_duration_minutes)
    for slot in available[1:]:
        if slot == prev + duration:
            prev = slot
        else:
            ranges.append((start, prev + duration))
            start = prev = slot
    ranges.append((start, prev + duration))
    return ranges

# Speech output: "Doctor is available from 2 PM to 4 PM and 5 PM to 6 PM"
# NOT: "Available at 2:00, 2:30, 3:00, 3:30, 4:00, 5:00, 5:30"
```

**Rules:**
- Patient MUST specify the day — agent never picks a day for the patient
- If doctor fully booked: "Doctor is not available from {date} to {date}. Please choose a date after {date}."
- If patient asks "available between 2–4?": check that range only, return ranges within it

---

## 8. Doctor Routing (Multi-Doctor Clinics)

**LLM prompt structure:**
```
You are a clinic intake router. Map patient complaint to correct doctor for BOOKING ONLY.
Do NOT diagnose. Do NOT recommend treatment.

Doctors: [{ name, specialization, routing_keywords }]
Patient said: "{complaint in Telugu/Hindi/English}"

Return JSON: { "doctor_id": "uuid"|null, "confidence": "high"|"low"|"none" }
```

**Routing rules:**
- `high` → route silently, book directly
- `low` → ask one clarifying question ("Is this about your teeth or something else?")
- `none` → route to `is_default_doctor=True` (general physician)
- No default doctor configured → list doctors by specialty, ask patient
- Single-doctor clinic → skip routing entirely
- Unknown complaint with default doctor → default doctor (general physician handles it)

**DB fields on `doctors`:**
- `specialization`: "general_physician" | "dentist" | "diabetologist" | "orthopedic" | ...
- `routing_keywords`: text[] e.g. ["teeth", "tooth", "cavity", "gums"]
- `is_default_doctor`: bool, exactly ONE per clinic

---

## 9. WhatsApp Flows

### Patient Booking via WhatsApp

```
State machine (whatsapp_sessions table):

── Fresh booking flow ──────────────────────────────────────────
GREETING       → collect name (→ WAITING_NAME)
WAITING_NAME   → store name, ask complaint (→ WAITING_DOCTOR if multi-doctor, else WAITING_SLOT)
WAITING_DOCTOR → LLM routing, confirm doctor (→ WAITING_SLOT)
WAITING_SLOT   → show available times/token info, patient picks (→ CONFIRM)
CONFIRM        → read back details, ask to confirm (→ CONFIRMED)
CONFIRMED      → create calendar + send WhatsApp confirm, end session

── Cancellation rebook flow (patient replies YES to cancellation WA) ──
CANCELLATION_REBOOK → system loads original complaint + doctor from cancelled token
                       → goes directly to WAITING_SLOT (doctor already known)
WAITING_SLOT        → same as fresh booking
CONFIRM             → same as fresh booking
CONFIRMED           → same as fresh booking
```
`session_data` JSONB carries: `{doctor_id, patient_name, complaint, is_rebook, cancelled_token_id}` for rebook sessions.

### Doctor Commands (inbound WhatsApp)

Messages to the branch WhatsApp number from a doctor's registered number:
```
"schedule off 20-May"         → cancel day + notify all existing patients (see Day Cancellation Flow below)
"schedule off 20-May to 25-May" → block date range, same notification flow for each affected day
"available 20-May"            → reply with that day's schedule
"cancel token 8"              → cancel specific patient (send patient WhatsApp + call if phone available)
"followup with Vinay about retainers, ask about discomfort"
  → creates followup_task in DB
  → looks up doctor_context Redis key for today's patient named "Vinay"
  → if multiple Vinays → "Token #5 or Token #12? Reply with number"
  → schedules outbound call
```

### Day Cancellation Flow (when doctor sends "schedule off {date}")

**Triggered by:** `schedule off {date}` or `schedule off {date} to {date}` doctor WhatsApp command.

**Step 1 — Immediate doctor acknowledgement:**
Reply to doctor: *"Blocking May 20. Checking for existing bookings..."*

**Step 2 — Find affected patients:**
Query `tokens WHERE doctor_id=X AND branch_id=Y AND date={date} AND status='waiting'`.

If 0 patients: block calendar, reply *"✅ May 20 blocked. No existing bookings to cancel."* → done.

If N patients: reply *"Found {N} booked patients. Cancelling and notifying them now..."*

**Step 3 — Cancel all bookings:**
For each affected token:
- Set `tokens.status = 'cancelled_by_clinic'`, set `tokens.cancellation_reason = 'doctor_unavailable'`
- Delete Google Calendar event (via `calendar_service.delete_event(event_id)`)
- Appointment-type only: `DECR slot:{doctor_id}:{branch_id}:{date}:{HHMM}` (free the slot for future rebooking)
- Token-type: no Redis change needed (token numbers don't get reclaimed)

**Step 4 — Notify each patient (parallel, fire-and-forget):**

**WhatsApp (sent to ALL patients who have a phone number — utility message, no consent check):**
```
Hi [Name], your appointment with Dr. [Doctor] at [Clinic] on [Date] has been cancelled.
The doctor is unavailable that day. We apologize for the inconvenience.
Your [Token #X / appointment at HH:MM] has been cancelled.

Would you like to book on another day when Dr. [Doctor] is available?
Reply YES to rebook now.
```

**Outbound call (sent to ALL patients who have a phone number — cancellation is service notification):**
```
"Hello, may I speak with [Name]? This is [Clinic Name] calling. 
We are calling to inform you that Dr. [Doctor] will not be available on [Date].
Your appointment has been cancelled. We are sorry for the inconvenience.
Would you like to book an appointment on another available day?"
```
- Patient says YES → continue directly into normal booking flow:
  - Check doctor's availability on other dates (same `check_availability` tool)
  - Patient picks a new date/slot → `assign_token` → `confirm_booking`
  - Same confirmation WhatsApp sent after rebook
- Patient says NO → *"Understood. Your appointment has been cancelled. Thank you."*

**Patients with no phone number:** WhatsApp-only → if no WhatsApp either (walk-in with no contact) → log as "no_contact", count them in doctor summary.

**Step 5 — Retry logic (if patient doesn't answer):**
- Attempt 1: immediately (30 seconds after cancellation)
- Attempt 2: +1 hour if no answer
- After 2 failed attempts: log as "unreachable", include in doctor summary

**Step 6 — Doctor summary (sent after all notifications dispatched):**
WhatsApp to doctor:
```
May 20 cancellation complete:
✅ 5 patients rebooked to new dates
❌ 2 patients declined rebook
📞 1 patient unreachable (2 attempts)
📵 0 patients had no contact info
```

**DB changes needed for this feature:**
- `tokens.status` enum: add `cancelled_by_clinic` (existing: waiting | attended | no_show)
- `tokens.cancellation_reason`: text | null (e.g. `'doctor_unavailable'`)

**Code location:** `backend/services/doctor_commands.py` — update `schedule_off()` handler to call `cancel_day_bookings()`.  
New function: `backend/services/cancel_day_bookings(doctor_id, branch_id, date)` — orchestrates steps 2–5.  
Outbound cancellation call reuses the same LiveKit agent flow as follow-up calls but with a different opening script and context (rebooking-enabled).

### Individual Token Cancellation ("cancel token 8")

Same as day cancellation but scoped to ONE token:
1. Look up `tokens WHERE doctor_id=X AND branch_id=Y AND token_number=8 AND date=today AND status='waiting'`
2. Set `status = 'cancelled_by_clinic'`, `cancellation_reason = 'doctor_cancelled'`
3. Delete Google Calendar event
4. Appointment-type: DECR slot Redis key
5. Send WhatsApp to patient: *"Your appointment with Dr. [X] today (Token #8) has been cancelled. Would you like to rebook?"*
6. Schedule outbound call to patient (same cancellation call flow — offer rebook)
7. Reply to doctor: *"Token #8 ([Patient Name]) cancelled and notified."*

### EOD Summary (APScheduler, 5:30 PM IST daily)
- Per doctor: "Today: 14 attended, 2 no-show, 1 absent. Reply to initiate follow-ups."
- Doctor replies with follow-up instructions

### Follow-up Call Flow
```
Doctor sends WhatsApp follow-up command
→ System looks up doctor_context:{doctor_id}:{date} (36h TTL)
→ Finds patient in today's list (scoped — not full DB search)
→ Disambiguates by token number if multiple patients with same name
→ Checks patient.followup_consent = True
→ Schedules outbound LiveKit SIP call:
    - If now 9 AM–5 PM: schedule in 30 minutes
    - If after 5 PM: schedule next day 9 AM
→ Outbound call: greet → ask specific_question → record response_summary
→ After call: WhatsApp doctor: "Feedback from {patient}: {response_summary}"

Retry logic (if no answer):
  Attempt 1 → no answer → retry +2 hours
  Attempt 2 → no answer → retry +2 hours
  Attempt 3 → no answer → status="unreachable"
            → WhatsApp doctor: "Could not reach {patient} after 3 attempts"
Max 3 attempts total.
```

---

## 10. Walk-In Registration (Receptionist PWA)

- Receptionist taps "+ Walk-in" button in PWA
- Selects doctor (cards show Token/Appt type)
- Enters patient name (required) + phone (optional, needed for WhatsApp + follow-ups)
- Enters brief complaint (optional)
- **Token-type doctor**: next token auto-assigned via Redis INCR (same as voice booking)
- **Appointment-type doctor**: shows available slots, receptionist picks
- `tokens.source = "walk_in"`
- No WhatsApp confirmation if phone not provided
- No follow-up calls if phone null or followup_consent=False
- Counted identically in all stats/analytics

---

## 11. Background Jobs (APScheduler)

All jobs run with Redis distributed lock: only one Render worker acquires `scheduler:leader` key (60s TTL, NX flag). Never use `--workers 2`.

| Job | Schedule | What it does |
|---|---|---|
| token_expiry | Every 2 min | Release held-but-unconfirmed tokens older than 10 min |
| eod_summary | 5:30 PM IST daily | Per-doctor summary WhatsApp to doctors |
| followup_calls | 9:00 AM IST daily | Process scheduled follow-up calls for the day |
| pre_appointment_reminder | Every 5 min | Call patients 30 min before appointment (opt-in, appointment-type doctors only) |
| billing_cycle_close | Daily midnight | Close billing cycles, trigger Razorpay charge for Solo plan |
| trial_expiry | Daily 10 AM | Pause service for expired trials, send payment link |

---

## 12. Clinic Onboarding Flow

```
Clinic owner signs up → Razorpay subscription created
→ provision_new_clinic():
    1. Create organization record
    2. Create branch record
    3. Vobiz Partner API: provision DID number → store vobiz_did_id
    4. Configure Vobiz call forwarding to LiveKit SIP endpoint
    5. Create WhatsApp webhook registration for branch number
    6. Google Calendar: create branch calendar, share with service account
    7. Send welcome WhatsApp to owner with setup instructions
    8. Create trial billing cycle
```

---

## 13. Data Isolation Rules (DPDP Act 2023)

**EVERY database query MUST filter by branch_id.** No exceptions.

```python
# WRONG:
db.query(Token).filter(Token.date == today).all()

# RIGHT:
db.query(Token).filter(Token.branch_id == branch_id, Token.date == today).all()
```

Receptionist JWT contains branch_id. Every API endpoint extracts branch_id from JWT and scopes all queries to it. The `branch_guard.py` middleware enforces this.

**WhatsApp branch identification:** Branch comes from `to_phone` (which number received the message), NOT `from_phone` (sender).

---

## 14. UI — Receptionist PWA

**Target:** Android mobile, used by receptionist at front desk  
**Host:** Cloudflare Pages (PWA, offline-capable)

### Layout
- **Header:** Clinic name + date + online/offline indicator + daily stats (Total/Waiting/Done/No-show)
- **Doctor tabs:** One tab per doctor, scrollable horizontally. Badge = **waiting count only**.
- **Per-tab patient list:**
  - Search bar (filters patients by name within tab)
  - "+ Walk-in" button (opens walk-in registration page)
  - Sections: "Now serving" | "Waiting" | "Completed"
  - **Every waiting patient** has Attend + No-show buttons (any order, not sequential)
  - Token-type: badge shows `#8`, `#9`, etc.
  - Appointment-type: badge shows `10:30`, `11:00`, etc.
  - Current patient: teal left border highlight
  - Walk-in patients: purple left border
  - Completed/no-show: faded, no buttons
- **Bottom nav:** Queue | Stats | More

### Walk-In Registration Page
- Back button → returns to queue
- Doctor selector (card grid, shows name + specialty + Token/Appt type)
- Token-type selected: next token auto-shown instantly
- Appointment-type selected: available slot picker appears
- Fields: Patient Name (required), Phone (optional), Complaint (optional)
- Submit: patient appears in queue immediately (optimistic update)

### Offline behavior
- Queue reads from cached data
- Attend/no-show actions queued locally
- Sync on reconnect
- Offline banner shown in header

---

## 15. UI — Owner Dashboard (Web)

**Target:** Desktop/tablet browser  
**Host:** Cloudflare Pages (same domain, different route)

### Clinic Owner Dashboard (Clinic/Multi plan)
- **Nav:** Vachanam logo | Branch name dropdown (switches branch) | Today/Week/Month | Alerts | Avatar
- **KPI row:** Patients today | Attendance rate (with bar) | No-shows | Minutes used vs plan limit
- **Weekly chart:** Bar chart, patient volume last 7 days, today highlighted
- **Source donut:** Voice / WhatsApp / Walk-in split (counts + mini bar chart)
- **Doctor cards (one per doctor):** Patients today | No-shows | This month | Avg call duration | Attendance rate bar
- **Plan usage:** Cycle dates + minutes bar + at-current-pace projection + renewal date
- **Recent bookings:** Last 6, source icon, patient name, doctor, token/time, status badge

**Multi-branch:** Branch dropdown in nav. Each branch loads independently. No combined view in MVP.

### Solo Doctor Dashboard
- **Nav:** Vachanam logo | Doctor name + specialty | Today/Week/Month | Alerts | Avatar
- **KPI row:** Patients today | Attendance rate | No-shows | **Free Mins Left** (highlighted teal — most important for variable billing)
- **Weekly chart:** Same, but "your clinic only" label
- **Busiest hours chart:** Horizontal bars by hour, shows peak hours for planning
- **Source breakdown:** Voice / WhatsApp / Walk-in counts
- **This Month's Bill card (prominent):** Free mins remaining | mins used bar | Base plan cost | Overage calculation | Projected total
- **Recent bookings:** Includes call duration per row (relevant for minute billing)

### Dashboard data rules
- No-shows card: shows count only, no revenue estimates
- Free mins: shows **remaining** count (not used), bar shows proportion consumed
- All numbers scoped to branch_id from JWT
- Date range picker switches all panels simultaneously

### Vachanam Admin Dashboard (Vinay's internal dashboard — NOT for clinics)

**Target:** Desktop, Vinay only. Route: `/admin` — protected by separate admin JWT claim.

**Tabs:** Overview | Clients | Costs | System

**Alert bar** — surfaced first: failed payments, trials expiring within 3 days, clinics above 80% minute usage.

**Business KPIs (5 cards):**
Revenue This Month | Gross Profit (with % margin) | Active Clients | In Trial | Churn This Month

**P&L Breakdown section (4 columns):**
- Revenue: plan fees (MRR) + overage charges
- Fixed costs: DID costs (N × ₹1,000) + Fly.io (₹840) + Render (₹588) + Neon (₹420)
- Variable costs: Sarvam STT/TTS + Vobiz streaming + LiveKit + Gemini + WhatsApp (all per minute)
- Net profit: gross profit + margin bar + trial cost absorbed this month

**Revenue + Profit trend chart** — dual bars (revenue + profit) per month, 6 months + 1 projected.

**Plan breakdown** — Solo/Clinic/Multi client count + their contribution to MRR.

**Client table (one row per clinic):**
Clinic name + city | Plan badge | Status badge | Minute usage bar + raw numbers | Renewal date | Revenue this cycle | My Cost (DID + infra share + variable + WhatsApp) | **Your Profit (₹ + %)** | Alert column

- Alert column: "💳 Payment failed" (red) | "⚡ X% minutes used" (amber above 80%) | "🕐 Trial expires in N days" (red)
- Rows tinted red/amber when alert is active
- Trial rows show negative profit (cost absorbed)
- Footer: lowest/highest margin clinic, total trial cost this month

**Cost formula per clinic:**
```
My Cost = DID cost + (infra_total / total_clients) + (minutes_used × ₹1.49) + (bookings × ₹0.23)
Your Profit = Revenue - My Cost
Margin % = Your Profit / Revenue × 100
```

**Variable cost breakdown (confirmed rates):**
- Sarvam STT: ₹0.50/min
- Sarvam TTS: ₹0.30/min
- Vobiz streaming: ₹0.65/min
- LiveKit + Gemini: ₹0.04/min
- **Total variable: ₹1.49/min**
- WhatsApp: ₹0.23/booking

---

## 16. Critical Code Patterns

### TTS sanitization (ALL TTS strings must go through this)
```python
clean_text = sanitize_for_tts("**Token #8** confirmed!")
# Result: "Token 8 confirmed"
await session.say(clean_text)
```

### LLM call with fallback
```python
async def call_llm(messages):
    try:
        return await gemini_call(messages)   # Primary
    except Exception as e:
        logger.error("gemini_failed_switching_to_openai", error=str(e))
        try:
            return await openai_call(messages)  # Fallback
        except Exception as e2:
            logger.critical("both_llms_failed", error=str(e2))
            return BOOKING_FAILURE_RESPONSE
```

### Every external call has retry
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=10))
async def call_external():
    ...
```

### Calendar-first, WhatsApp-second (never reverse)
```python
event_id = await calendar.create_event(...)    # RAISES on failure → booking fails
try:
    await meta_service.send_confirmation(...)  # Never fails booking
except Exception as e:
    logger.error("whatsapp_failed", error=str(e))
    await queue_retry(...)
```

### Structlog on every significant event
```python
logger.info("booking_confirmed", branch_id=branch_id, doctor_id=doctor_id,
            token_number=token_number, patient_phone=phone[-4:], via="voice")
logger.error("calendar_failed", branch_id=branch_id, error=str(e), attempt=n)
```
- **Never log full phone numbers** — always `phone[-4:]`
- **Never log patient names** — use patient_id

---

## 17. Deployment

| Service | Host | Config file |
|---|---|---|
| Voice agent | Fly.io bom (Mumbai) | `infra/fly.agent.toml` |
| Backend API | Render Starter ($7/month) | `infra/render.yaml` |
| Frontend PWA + Dashboard | Cloudflare Pages | Auto-deploy from git |
| Postgres | Neon ($5/month) | `DATABASE_URL` env var |
| Redis | Upstash (free tier) | `REDIS_URL` env var |

**Render workers:** MUST use `--workers 1` OR Redis leader lock. APScheduler jobs fire exactly once.

**Fly.io bom:** Shared across all clients. Fixed ₹840/month regardless of volume.

---

## 18. Cost Summary (Per Client)

### Variable cost per minute
```
Sarvam STT:      ₹0.50/min
Sarvam TTS:      ₹0.30/min
Vobiz streaming: ₹0.65/min
LiveKit VM share:₹0.03/min
Gemini Flash:    ~₹0.01/min
─────────────────────────────
Total:           ₹1.49/min
```

### Fixed per client per month
```
Vobiz DID:         ₹1,000
WhatsApp per msg:  ₹0.115 (utility)
WhatsApp per booking: ₹0.23 (2 msgs)
```

### Shared infrastructure (across ALL clients)
```
Fly.io bom: ₹840
Render:     ₹588
Neon:       ₹420
─────────────────
Total:      ₹1,848/month
```
