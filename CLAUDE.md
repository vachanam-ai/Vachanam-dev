# CLAUDE.md — Vachanam Master Context
## Read this entire file before writing a single line of code.
## This is not optional. This is not a summary. This is the law.

---

## WHAT YOU ARE BUILDING

**Vachanam** — AI-powered appointment booking for Indian clinics.
Tagline: *"Healing starts with being heard."*
Founder: Vinay Rongala, Hyderabad, India.
Domain: vachanam.in | Email: hello@vachanam.in

### The Problem
A clinic in Hyderabad gets 20–80 patient calls per day. The receptionist
manually answers each call, writes in a register, and misses 20–30% of
calls when busy. Each missed call = ₹300–500 lost consultation. At 10
missed calls/day that is ₹3,000–5,000 lost revenue daily.

### What Vachanam Does
A patient calls the clinic's existing number. That call is forwarded to
Vachanam's AI agent number. The AI answers in Telugu, understands the
patient's health issue, matches them to the correct doctor, checks
availability, assigns a token number atomically (no double-booking ever),
confirms by voice, creates a Google Calendar event, and sends WhatsApp
confirmation to both patient and doctor — all within 4 minutes.

The doctor manages their schedule entirely via WhatsApp commands. The
receptionist marks attendance on a mobile PWA. The clinic owner sees
analytics on a dashboard. Everything runs automatically.

### What Vachanam Does NOT Do
- No medical advice, diagnoses, prescriptions, or test recommendations
- No EMR/EHR storage of clinical records
- No insurance claim processing
- No patient payment collection
- No video consultations
- Not a replacement for the doctor-patient relationship

---

## PRICING (FINAL — DO NOT CHANGE WITHOUT INSTRUCTION)

### Plan 1: Solo — ₹1,999/month + ₹3/min
- Target: New clinics, 1 doctor, unknown/low volume
- DID: 1 Vobiz number included
- First 100 minutes free every month
- Voice: AI answers every inbound call (Telugu/Hindi/English)
- Features: Emergency detection, token booking, WhatsApp confirm,
  doctor schedule commands, receptionist PWA, 1 doctor only
- 4-minute AI call cap (AI wraps up at 4:00 exactly)
- Overage: billed per second at ₹3/min
- Your cost at 20 calls/day: ₹4,444/month | Revenue: ₹7,939 | Margin: 44%

### Plan 2: Clinic — ₹7,999/month flat ← MOST POPULAR
- Target: Active clinics, 2–3 doctors, ~20 calls/day
- DID: 1 Vobiz number included
- 2,100 min/month included (20 calls/day × 3.5 min × 30 days)
- Overage: ₹3/min beyond 2,100 min
- Features: everything in Solo + slot booking, outbound follow-ups,
  EOD summary, patient follow-up loop, analytics dashboard, 3 doctors
- Your cost at 20 calls/day: ₹4,452/month | Revenue: ₹7,999 | Margin: 44%

### Plan 3: Multi — ₹16,999/month flat
- Target: Busy clinics, 4–6 doctors, ~50 calls/day
- DID: Up to 2 numbers (2 branches)
- 4,200 min/month included (20 calls/day × 2 DIDs × 3.5 min × 30)
- Overage: ₹2.50/min beyond 4,200 min
- Features: everything in Clinic + 6 doctors, ambulance transfer,
  multi-doctor routing, priority support, analytics CSV export
- Extra branch: ₹7,999/month
- Your cost at 40 calls/day: ₹8,719/month | Revenue: ₹16,999 | Margin: 49%

### Free Trial: 14 days, no credit card, 1,000 min limit
- Day 12: Razorpay payment link auto-sent via WhatsApp
- Day 14: Service pauses if not paid
- Your cost per trial: ~₹2,675 absorbed (DID ₹1,000 + infra ₹185 + 1,000 min × ₹1.49)

---

## COMPLETE TECH STACK (FINAL — DO NOT DEVIATE)

| Layer | Tool | Version | Why chosen |
|---|---|---|---|
| STT | Sarvam Saaras v3 | latest | Only viable Telugu STT. 99.99% uptime. |
| TTS | Sarvam Bulbul v3 | latest | Only natural Telugu TTS. 99.99% uptime. |
| LLM primary | Gemini 2.5 Flash | latest | Best Telugu reasoning. Generous free tier. |
| LLM fallback | GPT-4o mini | latest | Auto-fallback if Gemini fails. 99.99% uptime. |
| Voice pipeline | LiveKit Agents | 1.4.x | Self-hosted. Open source. SIP + WebSocket. |
| Telephony | Vobiz | — | Indian DID. ₹0.65/min streaming. Partner API. |
| Token locking | Upstash Redis | 7.x | Managed. Free tier. Atomic INCR. |
| Calendar | Google Calendar API | v3 | Free. Doctors already use it. |
| WhatsApp | Meta Cloud API | v20+ | Zero BSP fee. Direct integration. |
| Database | Neon Postgres | — | Serverless. Built-in pooling. $5/month. |
| ORM | SQLAlchemy | 2.x | Async with asyncpg. |
| Migrations | Alembic | latest | — |
| Backend | FastAPI | 0.110+ | Async Python. |
| Scheduler | APScheduler | 3.x | Background jobs. |
| Agent host | Fly.io bom | — | Only India-region PaaS. Mumbai. |
| API host | Render | — | Reliable HTTP. Always-on $7/month. |
| Frontend | React + Vite | 18.x | PWA. Offline capable. |
| CSS | TailwindCSS | 3.x | Utility classes. |
| Frontend host | Cloudflare Pages | — | Free. 99.99%. Global CDN. |
| Payments | Razorpay | — | India standard. UPI + cards. |
| Monitoring | UptimeRobot | — | Free. 2-min checks. SMS. |
| Logging | Structlog | latest | JSON structured logs always. |
| Retry | Tenacity | latest | All external API calls. |

---

## VERIFIED COSTS (FROM OFFICIAL SOURCES, MAY 2026)

### Per-minute variable costs
```
Sarvam STT:        ₹0.50/min  (₹30/hour — sarvam.ai/api-pricing)
Sarvam TTS:        ₹0.30/min  (₹15/10K chars — sarvam.ai/api-pricing)
Vobiz streaming:   ₹0.65/min  (VERIFIED — indiahood.com seed announcement)
LiveKit VM share:  ₹0.03/min  (₹840 VM ÷ 20 clients ÷ avg minutes)
Gemini 2.5 Flash:  ₹0.01/min  (~$0.15/1M tokens input — aistudio.google.com)
───────────────────────────────────────────────────────────────────────
TOTAL COST/MIN:    ₹1.49/min
```

### Fixed costs per clinic per month
```
Vobiz DID number:    ₹1,000  (VERIFIED by Vinay — confirmed with Vobiz)
WhatsApp per msg:    ₹0.115  (utility messages — Meta official rate)
WhatsApp per booking: ₹0.23  (2 messages: patient + doctor)
```

### Infrastructure (shared across all clients)
```
Fly.io bom VM:       ₹840/month total  (~$10, shared-cpu-2x 1GB)
Render web service:  ₹588/month total  ($7 Starter plan)
Neon Postgres:       ₹420/month total  ($5 Launch plan)
Upstash Redis:       ₹0               (500K commands/month free)
Google Calendar:     ₹0               (free API)
Cloudflare Pages:    ₹0               (free static hosting)
UptimeRobot:         ₹0               (free plan)
```

### Your total monthly burn before first client
```
Fly.io + Render + Neon + Vobiz test DID + domain/email = ₹3,048/month
```

---

## ENVIRONMENT VARIABLES — ALL 26 REQUIRED

```bash
# ── AI ────────────────────────────────────────────────────────────────
SARVAM_API_KEY=                   # from sarvam.ai dashboard
OPENAI_API_KEY=                   # from platform.openai.com (Fallback LLM — GPT-4o mini)
GEMINI_API_KEY=                   # from aistudio.google.com (Primary LLM — Gemini 2.5 Flash)

# ── LiveKit (self-hosted on Fly.io bom) ───────────────────────────────
LIVEKIT_URL=wss://vachanam-agent.fly.dev
LIVEKIT_API_KEY=                  # generated during LiveKit server setup
LIVEKIT_API_SECRET=               # generated during LiveKit server setup

# ── Telephony (Vobiz SIP trunk) ───────────────────────────────────────
VOBIZ_SIP_DOMAIN=                 # e.g. abc123.sip.vobiz.ai (trunk address in LiveKit)
VOBIZ_SIP_USERNAME=               # auth credential from Vobiz trunk setup
VOBIZ_SIP_PASSWORD=               # auth credential from Vobiz trunk setup
VOBIZ_DID_NUMBER=                 # purchased DID in E.164 format e.g. +914066XXXXXX
VOBIZ_PARTNER_AUTH_ID=            # your master partner account ID (for provisioning)
VOBIZ_PARTNER_AUTH_TOKEN=         # your master partner token (for provisioning)

# ── WhatsApp (Meta Cloud API — no BSP) ───────────────────────────────
META_ACCESS_TOKEN=                # permanent token from Meta Business
META_PHONE_NUMBER_ID=             # from WhatsApp Business dashboard
META_WABA_ID=                     # WhatsApp Business Account ID
META_WEBHOOK_VERIFY_TOKEN=        # any random string you choose
META_APP_SECRET=                  # for verifying webhook signatures

# ── Google ────────────────────────────────────────────────────────────
GOOGLE_OAUTH_CLIENT_ID=           # from Google Cloud Console
GOOGLE_OAUTH_CLIENT_SECRET=       # from Google Cloud Console
GOOGLE_APPLICATION_CREDENTIALS=./google-service-account.json
GOOGLE_CALENDAR_SERVICE_EMAIL=    # service account email (xxx@xxx.iam.gserviceaccount.com)

# ── Database ──────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://user:pass@host/vachanam
# Local dev: postgresql+asyncpg://vachanam:localdev123@localhost:5432/vachanam_dev

# ── Redis ─────────────────────────────────────────────────────────────
REDIS_URL=                        # from Upstash dashboard (rediss://...)
# Local dev: redis://localhost:6379

# ── Auth ──────────────────────────────────────────────────────────────
JWT_SECRET=                       # openssl rand -hex 32
JWT_EXPIRE_HOURS=24

# ── Payment ───────────────────────────────────────────────────────────
RAZORPAY_KEY_ID=                  # from Razorpay dashboard
RAZORPAY_KEY_SECRET=              # from Razorpay dashboard
RAZORPAY_WEBHOOK_SECRET=          # set in Razorpay dashboard
RAZORPAY_PLAN_SOLO_ID=            # create in Razorpay → Plans
RAZORPAY_PLAN_CLINIC_ID=          # create in Razorpay → Plans
RAZORPAY_PLAN_MULTI_ID=           # create in Razorpay → Plans

# ── App config ────────────────────────────────────────────────────────
APP_ENV=development               # development | production
BASE_URL=http://localhost:8000
FRONTEND_URL=http://localhost:3000
ADMIN_PHONE=+919XXXXXXXXX         # your WhatsApp — all alerts go here
LOG_LEVEL=debug
```

---

## PROJECT STRUCTURE — EXACT AND FINAL

```
vachanam/
├── CLAUDE.md                         ← THIS FILE — read first always
├── PHASE_0_ENVIRONMENT.md            ← Phase 0 instructions
├── PHASE_1_VOICE_AGENT.md            ← Phase 1 instructions
├── PHASE_2_BACKEND.md                ← Phase 2 instructions
├── PHASE_3_FRONTEND.md               ← Phase 3 instructions
├── PHASE_4_ONBOARDING.md             ← Phase 4 instructions
├── PHASE_5_PRODUCTION.md             ← Phase 5 instructions
├── .env.example                      ← all 25 vars, empty values
├── .env                              ← NEVER COMMIT THIS
├── .gitignore
├── docker-compose.yml                ← local dev only
│
├── agent/                            ← Voice agent (runs on Fly.io bom)
│   ├── __init__.py
│   ├── agent.py                      ← LiveKit entrypoint
│   ├── session_state.py              ← per-call state dataclass
│   ├── requirements.txt
│   ├── prompts/
│   │   ├── __init__.py
│   │   └── system_prompt.py          ← Telugu prompt builder
│   ├── services/
│   │   ├── __init__.py
│   │   ├── tts_sanitizer.py          ← sanitize before TTS
│   │   └── emergency.py              ← MVP: keyword detect, give branch.emergency_contact
│   └── tools/
│       ├── __init__.py
│       └── booking_tools.py          ← 4 LLM function tools
│
├── backend/                          ← FastAPI (runs on Render)
│   ├── __init__.py
│   ├── main.py
│   ├── config.py                     ← Pydantic settings
│   ├── database.py                   ← SQLAlchemy async engine
│   ├── models/
│   │   ├── __init__.py
│   │   └── schema.py                 ← all 9 DB tables (see design doc for schema)
│   ├── routers/
│   │   ├── __init__.py
│   │   ├── auth.py                   ← Google OAuth + JWT
│   │   ├── queue.py                  ← receptionist endpoints
│   │   ├── whatsapp.py               ← Meta webhook handler
│   │   ├── dashboard.py              ← clinic owner analytics
│   │   ├── admin.py                  ← Vachanam admin (Vinay only, is_admin JWT claim)
│   │   └── onboarding.py             ← Razorpay + clinic setup
│   ├── services/
│   │   ├── __init__.py
│   │   ├── token_service.py          ← Redis INCR atomic
│   │   ├── calendar_service.py       ← Google Calendar CRUD
│   │   ├── meta_service.py           ← WhatsApp send via Meta API
│   │   ├── whatsapp_agent.py         ← patient WA state machine
│   │   ├── doctor_commands.py        ← doctor WA NLP parser
│   │   ├── cancel_day_bookings.py    ← day/token cancellation + patient notify orchestrator
│   │   ├── vobiz_partner.py          ← Vobiz Partner API wrapper
│   │   └── onboarding_service.py     ← provision_new_clinic()
│   ├── middleware/
│   │   ├── __init__.py
│   │   ├── auth_middleware.py        ← JWT validation
│   │   └── branch_guard.py           ← branch_id scoping enforcement
│   └── jobs/
│       ├── __init__.py
│       ├── token_expiry.py           ← APScheduler every 2 min
│       ├── eod_summary.py            ← APScheduler 5:30 PM IST
│       ├── followup_calls.py         ← APScheduler 9 AM IST
│       ├── pre_appt_reminder.py      ← APScheduler every 5 min (30-min pre-call, appt-type only)
│       ├── billing_cycle.py          ← APScheduler daily midnight (close cycle, charge Solo)
│       └── trial_expiry.py           ← APScheduler daily 10 AM (pause + send payment link)
│
├── frontend/                         ← React PWA (Cloudflare Pages)
│   ├── package.json
│   ├── vite.config.js
│   ├── tailwind.config.js
│   ├── public/
│   │   └── manifest.json             ← PWA manifest
│   └── src/
│       ├── main.jsx
│       ├── App.jsx
│       ├── api/
│       │   └── client.js             ← axios + JWT interceptor
│       ├── hooks/
│       │   ├── useAuth.js
│       │   ├── useQueue.js           ← React Query + optimistic
│       │   └── useDashboard.js
│       ├── pages/
│       │   ├── Login.jsx
│       │   ├── Queue.jsx
│       │   ├── WalkIn.jsx            ← walk-in registration (doctor picker + slot/token)
│       │   ├── Dashboard.jsx         ← clinic owner dashboard (Solo/Clinic/Multi layout switch)
│       │   └── AdminDashboard.jsx    ← Vachanam admin (Vinay only — P&L, all clients)
│       └── components/
│           ├── PatientCard.jsx       ← attend/no-show + optimistic update
│           ├── HeroNumber.jsx
│           ├── WeeklyChart.jsx
│           └── OfflineBanner.jsx
│
├── infra/
│   ├── fly.agent.toml                ← voice agent deploy config
│   ├── render.yaml                   ← backend deploy config
│   ├── Dockerfile.agent              ← agent container
│   └── Dockerfile.backend            ← backend container (local use)
│
└── tests/
    ├── conftest.py
    ├── unit/
    │   ├── test_tts_sanitizer.py     ← 11 tests — must all pass
    │   ├── test_emergency.py         ← 12 tests — must all pass
    │   └── test_auth.py
    ├── integration/
    │   ├── test_booking_flow.py
    │   ├── test_whatsapp_flow.py
    │   └── test_eod_followup.py
    └── edge_cases/
        ├── test_concurrent_tokens.py ← critical — 5 callers simultaneously
        └── test_data_isolation.py    ← critical — branch_id scoping
```

---

## THE 10 ABSOLUTE RULES — NEVER BREAK THESE

### RULE 1: Every database query MUST include branch_id
```python
# WRONG — will expose one clinic's data to another
db.query(Token).filter(Token.date == today).all()

# RIGHT — always scope to branch
db.query(Token).filter(
    Token.branch_id == branch_id,
    Token.date == today
).all()
```
This is not a suggestion. Patient data isolation is a legal requirement
under India's DPDP Act 2023. Breach = potential criminal liability.

### RULE 2: Token assignment uses ONLY Redis INCR — never DB count
```python
# WRONG — race condition, two callers get same token
count = db.query(Token).filter(...).count()
next_token = count + 1

# RIGHT — Redis INCR is atomic, two callers always get different numbers
token_number = await redis.incr(f"token:{doctor_id}:{branch_id}:{date}")
if token_number > limit:
    await redis.decr(f"token:{doctor_id}:{branch_id}:{date}")
    return None  # full
```

### RULE 3: Token held in session until patient explicitly confirms
```python
# Token is HELD (Redis incremented) after assign_token() call
# Token is CONFIRMED only after confirm_booking() call
# If call drops without confirmation: IMMEDIATELY release via redis.decr()

@session.on("disconnected")
async def on_disconnect():
    if state.token_held and not state.token_confirmed:
        await redis.decr(state.token_redis_key)
        logger.warning("token_released_on_disconnect",
                       token=state.token_number,
                       branch_id=state.branch_id)
```

### RULE 4: Calendar first, WhatsApp second — never reverse
```python
# Calendar failure = booking failure (raise exception)
event_id = await calendar.create_event(...)  # RAISES if fails

# WhatsApp failure = notification failure (log, retry, never fail booking)
try:
    await meta_service.send_confirmation(...)
except Exception as e:
    logger.error("whatsapp_failed", error=str(e))
    await queue_retry(...)  # retry in background
# booking is still successful even if WhatsApp fails
```

### RULE 5: Branch context comes from receiving WhatsApp number
```python
# WRONG — using sender phone for branch
branch = db.get_branch_by_phone(from_phone)

# RIGHT — branch comes from which WhatsApp number received the message
branch = await db.get_branch_by_whatsapp_number(to_phone)
sender_role = await db.get_role_by_phone(from_phone)
```

### RULE 6: EVERY TTS string goes through sanitize_for_tts()
```python
# WRONG — markdown sounds terrible on the phone
await session.say("**Token #8** confirmed!")

# RIGHT — always sanitize
clean_text = sanitize_for_tts("**Token #8** confirmed!")
await session.say(clean_text)
# Result: "Token 8 confirmed" — sounds natural
```

### RULE 7: Emergency MVP — keyword detect only, give branch emergency_contact
```python
# MVP has NO TYPE_1/TYPE_2 classification. Do not implement it.
# If patient mentions ANY emergency keywords at any point:
#   → Say: "I understand this is urgent. Our emergency contact is: {branch.emergency_contact}"
#   → Continue booking as normal (urgent priority)
#   → Never suggest 108. Never classify. Never transfer call.

# emergency.py detects keywords only (e.g. "heart attack", "chest pain", "unconscious")
# branch.emergency_contact is shown — it's the clinic's own emergency number
# Full TYPE_1/TYPE_2 classification is a post-MVP feature
```

### RULE 8: Every external API call has retry + graceful fallback
```python
from tenacity import retry, stop_after_attempt, wait_exponential

@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10)
)
async def call_external_api():
    ...

# If all 3 retries fail → graceful patient message, never crash agent
```

### RULE 9: LLM primary = Gemini 2.5 Flash → fallback = GPT-4o mini
```python
# Primary: Gemini 2.5 Flash — better Telugu performance.
# Fallback: GPT-4o mini — activates automatically if Gemini fails.

async def call_llm(messages: list) -> str:
    try:
        return await gemini_call(messages)   # PRIMARY — Gemini 2.5 Flash
    except Exception as e:
        logger.error("gemini_failed_switching_to_openai", error=str(e))
        try:
            return await openai_call(messages)  # FALLBACK — GPT-4o mini
        except Exception as e2:
            logger.critical("both_llms_failed", error=str(e2))
            return BOOKING_FAILURE_RESPONSE  # graceful Telugu message
```

### RULE 10: Structlog JSON for every significant event
```python
logger.info("booking_confirmed",
    branch_id=branch_id,
    doctor_id=doctor_id,
    token_number=token_number,
    patient_phone=patient_phone[-4:],  # last 4 digits only — privacy
    via="voice",
    duration_seconds=call_duration
)

logger.error("calendar_failed",
    branch_id=branch_id,
    error=str(e),
    attempt=attempt_number
)
```

---

## CODE QUALITY STANDARDS

### Python
- Type hints on every function signature
- Pydantic models for every request/response shape
- Never `print()` — always `logger`
- Never bare `except:` — always `except SpecificException as e:`
- Never hardcode any key, URL, phone number, or secret
- Never commit `.env` or `google-service-account.json`
- Never return HTML from an API — always JSON

### Logging (mandatory format)
```python
import structlog
logger = structlog.get_logger()

# Every call lifecycle event:
logger.info("call_started", branch_id=branch_id, caller=phone[-4:])
logger.info("token_assigned", token=n, doctor_id=did, via="voice")
logger.info("booking_confirmed", token=n, branch_id=bid)
logger.warning("token_released_on_disconnect", token=n)
logger.error("sarvam_stt_failed", error=str(e), attempt=n)
logger.critical("emergency_type1_detected", branch_id=bid, caller=phone[-4:])
```

### Git commit messages
```
feat: add Redis atomic token assignment with limit check
fix: release token immediately on call disconnect
test: add 5 concurrent callers edge case
docs: update API endpoints in PHASE_2_BACKEND.md
```

---

## WHAT TO DO WHEN YOU ARE UNSURE

Before writing any function, ask yourself:
1. Does every DB query filter by `branch_id`? → If no, fix first.
2. Does this token operation use Redis INCR? → If no, stop and rethink.
3. Does this WhatsApp send have try/except that does NOT fail the booking? → If no, fix first.
4. Does this TTS string go through `sanitize_for_tts()`? → If no, fix first.
5. Is this secret read from `settings.xxx`? → If no, move it to config.
6. Does this external API call have `@retry`? → If no, add it.
7. Does this function have structlog on every success and error? → If no, add it.

If any answer is no — fix it before moving on. Do not build on broken foundations.

---

## BUILD ORDER — FOLLOW EXACTLY

```
Phase 0: Environment         → PHASE_0_ENVIRONMENT.md
Phase 1: Voice agent core    → PHASE_1_VOICE_AGENT.md
Phase 2: Backend + WhatsApp  → PHASE_2_BACKEND.md
Phase 3: Frontend PWA        → PHASE_3_FRONTEND.md
Phase 4: Clinic onboarding   → PHASE_4_ONBOARDING.md
Phase 5: Production deploy   → PHASE_5_PRODUCTION.md
```

Do NOT skip phases. Do NOT start Phase 2 until Phase 1 exit criteria pass.
Each phase has a checklist at the end. Every item must be checked before moving on.

---

## UPTIME COMMITMENTS

| Service | Realistic uptime | Fallback |
|---|---|---|
| Sarvam STT/TTS | 99.99% | Graceful callback message |
| Gemini 2.5 Flash | 99.9% | Auto-switch to GPT-4o mini |
| GPT-4o mini (fallback) | 99.99% | BOOKING_FAILURE_RESPONSE if both LLMs fail |
| Fly.io Mumbai | 99.0–99.5% | Singapore standby VM |
| Render backend | 99.9% | Auto-restart |
| Neon Postgres | 99.9% | Daily automatic backups |
| Vobiz | 99.9% | Retry + graceful "call back" message to patient |
| Overall app | 99.4% | All mitigations active |

---

## SENSITIVE DATA RULES

1. Never log full phone numbers — always last 4 digits only: `phone[-4:]`
2. Never log full patient names — use patient_id only in logs
3. Never store medical details in calendar events — name + phone + token only
4. Never put health information in WhatsApp messages — booking details only
5. All call recordings require explicit patient consent at call start
6. Redis keys expire at end of day + 1 hour buffer — never persist token data
