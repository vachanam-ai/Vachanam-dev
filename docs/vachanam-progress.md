# Vachanam — Build Progress Tracker
**Last updated:** 2026-05-15  
**Current phase:** Phase 0 (Environment) — NOT STARTED  
**Design status:** ✅ COMPLETE — all sections approved by Vinay  

> **For Claude:** Read `docs/superpowers/specs/2026-05-15-vachanam-complete-design.md` first.  
> That file has the full architecture. This file tracks what's built vs what's left.  
> Key overrides from CLAUDE.md are listed at the top of the design doc — check them before coding.

---

## Legend
- ✅ Done (designed + built + tested)
- 🎨 Designed only (not yet built)
- 🔨 In progress
- ⬜ Not started
- ❌ Blocked

---

## Overall Phase Status

| Phase | Name | Status | Exit Criteria Met? |
|---|---|---|---|
| Phase 0 | Environment Setup | ⬜ Not started | No |
| Phase 1 | Voice Agent Core | ⬜ Not started | No |
| Phase 2 | Backend + WhatsApp | ⬜ Not started | No |
| Phase 3 | Frontend PWA | ⬜ Not started | No |
| Phase 4 | Clinic Onboarding | ⬜ Not started | No |
| Phase 5 | Production Deploy | ⬜ Not started | No |

---

## Phase 0 — Environment Setup

**Goal:** All services running locally, all env vars set, DB migrations complete.

| Task | Status | Notes |
|---|---|---|
| Create project directory structure (exact per CLAUDE.md) | ⬜ | |
| Create `.env` from `.env.example` with all 25 vars | ⬜ | See CLAUDE.md for full list |
| `docker-compose.yml` for local Postgres + Redis | ⬜ | |
| Neon Postgres: create database | ⬜ | |
| Upstash Redis: create instance | ⬜ | |
| Alembic: create all 9 migrations | ⬜ | See schema in design doc (9 tables: organizations, branches, doctors, patients, tokens, calls, followup_tasks, billing_cycles, whatsapp_sessions) |
| Sarvam API key: get from sarvam.ai | ⬜ | |
| Gemini API key: get from aistudio.google.com | ⬜ | Primary LLM |
| OpenAI API key: get from platform.openai.com | ⬜ | Fallback LLM |
| Google Cloud: create project, enable Calendar API | ⬜ | |
| Google: create service account, download JSON | ⬜ | |
| Meta: get permanent access token + phone number ID | ⬜ | |
| Vobiz: get partner API credentials | ⬜ | |
| Razorpay: create account, get keys | ⬜ | |
| LiveKit: self-host on Fly.io bom | ⬜ | |
| Verify all services reachable from local machine | ⬜ | |
| Seed admin account (Vinay's Google email → is_admin=True in JWT) | ⬜ | Run once after first migration — required for AdminDashboard access |

**Exit criteria:** `docker-compose up` runs cleanly, migrations apply, all env vars valid.

---

## Phase 1 — Voice Agent Core

**Goal:** AI answers calls in Telugu, books appointments, handles all routing scenarios.

### Core Agent (`agent/`)

| Task | Status | File | Notes |
|---|---|---|---|
| `agent.py` — LiveKit entrypoint | ⬜ | `agent/agent.py` | |
| `session_state.py` — per-call dataclass | ⬜ | `agent/session_state.py` | |
| `system_prompt.py` — Telugu prompt builder | ⬜ | `agent/prompts/system_prompt.py` | |
| `tts_sanitizer.py` — strip markdown before TTS | ⬜ | `agent/services/tts_sanitizer.py` | 11 tests must pass |
| `emergency.py` — MVP: detect keywords, give branch contact | ⬜ | `agent/services/emergency.py` | No TYPE_1/TYPE_2 in MVP |
| `booking_tools.py` — 4 LLM function tools | ⬜ | `agent/tools/booking_tools.py` | See below |

### 4 LLM Booking Tools

| Tool | Status | What it does |
|---|---|---|
| `route_to_doctor(complaint, clinic_doctors)` | ⬜ | LLM symptom → doctor_id, confidence |
| `check_availability(doctor_id, date, query_start?, query_end?)` | ⬜ | Returns available ranges as speech string |
| `assign_token(doctor_id, branch_id, date)` | ⬜ | Redis INCR, returns token number or "full" |
| `confirm_booking(token_id, patient_name, followup_consent)` | ⬜ | Triggers calendar + WhatsApp |

### Tests (`tests/unit/`)

| Test | Status | Notes |
|---|---|---|
| `test_tts_sanitizer.py` — 11 tests | ⬜ | Must all pass before Phase 1 complete |
| `test_emergency.py` — 12 tests | ⬜ | Must all pass |
| `test_auth.py` | ⬜ | |

### Integration Tests

| Test | Status | Notes |
|---|---|---|
| `test_booking_flow.py` — full voice call simulation | ⬜ | |
| `test_concurrent_tokens.py` — 5 callers simultaneously | ⬜ | CRITICAL |

**Exit criteria:** All unit tests pass. Concurrent token test passes (5 callers, no duplicate tokens). Can complete a voice booking end-to-end in dev.

---

## Phase 2 — Backend + WhatsApp

**Goal:** FastAPI backend handles all routes. WhatsApp state machine works. Doctor commands work. Scheduled jobs run.

### Database + Config

| Task | Status | File |
|---|---|---|
| `config.py` — Pydantic settings, all 25 env vars | ⬜ | `backend/config.py` |
| `database.py` — SQLAlchemy async engine | ⬜ | `backend/database.py` |
| `schema.py` — all 9 DB models | ⬜ | `backend/models/schema.py` |

### Services

| Task | Status | File | Notes |
|---|---|---|---|
| `token_service.py` — Redis INCR/DECR | ⬜ | `backend/services/token_service.py` | Both token + slot booking |
| `calendar_service.py` — Google Calendar CRUD | ⬜ | `backend/services/calendar_service.py` | |
| `meta_service.py` — WhatsApp send via Meta API | ⬜ | `backend/services/meta_service.py` | |
| `whatsapp_agent.py` — patient WA state machine | ⬜ | `backend/services/whatsapp_agent.py` | GREETING→CONFIRMED |
| `doctor_commands.py` — doctor WA NLP parser | ⬜ | `backend/services/doctor_commands.py` | schedule, followup, cancel token |
| `cancel_day_bookings.py` — day cancellation orchestrator | ⬜ | `backend/services/cancel_day_bookings.py` | Called by schedule_off command; cancels tokens, deletes calendar events, notifies patients via WA + call, reports to doctor |
| `vobiz_partner.py` — Vobiz Partner API wrapper | ⬜ | `backend/services/vobiz_partner.py` | |
| `onboarding_service.py` — provision_new_clinic() | ⬜ | `backend/services/onboarding_service.py` | |

### Routers (API Endpoints)

| Router | Status | File | Key endpoints |
|---|---|---|---|
| `auth.py` | ⬜ | `backend/routers/auth.py` | Google OAuth + JWT |
| `queue.py` | ⬜ | `backend/routers/queue.py` | GET /queue, PATCH /token/{id}/attend, PATCH /token/{id}/no-show, POST /walkin |
| `whatsapp.py` | ⬜ | `backend/routers/whatsapp.py` | POST /webhook/whatsapp (Meta webhook) |
| `dashboard.py` | ⬜ | `backend/routers/dashboard.py` | GET /stats/today, GET /stats/weekly, GET /doctors/stats |
| `onboarding.py` | ⬜ | `backend/routers/onboarding.py` | POST /signup, POST /webhook/razorpay |
| `admin.py` | ⬜ | `backend/routers/admin.py` | GET /admin/stats, GET /admin/clients, GET /admin/pnl — is_admin JWT claim required |

### Middleware

| Task | Status | File |
|---|---|---|
| `auth_middleware.py` — JWT validation | ⬜ | `backend/middleware/auth_middleware.py` |
| `branch_guard.py` — branch_id scoping enforcement | ⬜ | `backend/middleware/branch_guard.py` |

### Background Jobs (APScheduler)

| Job | Status | File | Schedule |
|---|---|---|---|
| `token_expiry.py` | ⬜ | `backend/jobs/token_expiry.py` | Every 2 min |
| `eod_summary.py` | ⬜ | `backend/jobs/eod_summary.py` | 5:30 PM IST |
| `followup_calls.py` | ⬜ | `backend/jobs/followup_calls.py` | 9 AM IST |
| `pre_appt_reminder.py` | ⬜ | `backend/jobs/pre_appt_reminder.py` | Every 5 min — calls patient 30 min before appointment (opt-in, appt-type only) |
| `billing_cycle.py` | ⬜ | `backend/jobs/billing_cycle.py` | Daily midnight — closes cycle, triggers Razorpay Solo charge |
| `trial_expiry.py` | ⬜ | `backend/jobs/trial_expiry.py` | Daily 10 AM — pause service + send payment link for expired trials |
| Redis scheduler lock (NX flag, 60s TTL) | ⬜ | `backend/main.py` startup | Prevents dual-firing |

### Integration Tests

| Test | Status |
|---|---|
| `test_whatsapp_flow.py` — full WA booking simulation | ⬜ |
| `test_eod_followup.py` — EOD summary + follow-up call | ⬜ |
| `test_data_isolation.py` — branch_id scoping | ⬜ |
| `test_day_cancellation.py` — cancel day, notify all patients, rebook flow | ⬜ |

**Exit criteria:** WhatsApp booking works end-to-end. Doctor commands parse correctly. APScheduler jobs fire once (not twice). All integration tests pass.

---

## Phase 3 — Frontend PWA

**Goal:** Receptionist PWA works on Android. Owner dashboard renders correct data.

### Receptionist PWA (`frontend/src/pages/Queue.jsx`)

| Task | Status | Component | Notes |
|---|---|---|---|
| Doctor tabs (scrollable, waiting count badge) | ⬜ | `Queue.jsx` | |
| Per-doctor patient list (token or time badge) | ⬜ | `PatientCard.jsx` | |
| Attend / No-show buttons (any patient, any order) | ⬜ | `PatientCard.jsx` | Optimistic update |
| Search bar (filter patients by name) | ⬜ | `Queue.jsx` | |
| Walk-in registration page | ⬜ | `WalkIn.jsx` | Doctor picker + slot/token |
| Offline banner | ⬜ | `OfflineBanner.jsx` | |
| Offline queue caching + sync on reconnect | ⬜ | `useQueue.js` | |
| PWA manifest + service worker | ⬜ | `public/manifest.json` | |

### Owner Dashboard (`frontend/src/pages/Dashboard.jsx`)

| Task | Status | Notes |
|---|---|---|
| KPI cards row | ⬜ | |
| Weekly bar chart | ⬜ | `WeeklyChart.jsx` |
| Booking source breakdown | ⬜ | |
| Per-doctor cards | ⬜ | Clinic/Multi plan only |
| Busiest hours chart | ⬜ | Solo plan only |
| Plan usage + bill projection | ⬜ | |
| Recent bookings list | ⬜ | |
| Branch selector dropdown (multi-branch) | ⬜ | |
| Solo vs Clinic/Multi layout switch | ⬜ | Based on plan in JWT |
| Date range picker (Today/Week/Month) | ⬜ | |

### Admin Dashboard (`frontend/src/pages/AdminDashboard.jsx`)

| Task | Status | Notes |
|---|---|---|
| Alert bar (failed payments, expiring trials, >80% min usage) | ⬜ | |
| Business KPIs (Revenue, Gross Profit, Active, Trial, Churn) | ⬜ | |
| P&L breakdown section (Revenue / Fixed costs / Variable costs / Net profit) | ⬜ | Cost formula: DID + infra share + (min × ₹1.49) + WhatsApp |
| Revenue + Profit trend chart (6 months + projected) | ⬜ | |
| Plan breakdown (Solo/Clinic/Multi counts + MRR) | ⬜ | |
| Client table with Your Profit column (₹ + %) | ⬜ | My Cost = DID + infra + variable + WhatsApp per clinic |
| Admin route protection | ⬜ | Separate `is_admin` JWT claim — Vinay's account only |

### Auth

| Task | Status | Notes |
|---|---|---|
| `Login.jsx` — Google OAuth flow | ⬜ | |
| `useAuth.js` — JWT store + refresh | ⬜ | |
| `client.js` — axios + JWT interceptor | ⬜ | |

**Exit criteria:** PWA installable on Android. Offline attend/no-show works. Dashboard loads correct data for each plan type.

---

## Phase 4 — Clinic Onboarding

**Goal:** New clinic can sign up, pay, and go live without manual intervention.

| Task | Status | Notes |
|---|---|---|
| Signup form (React) | ⬜ | Name, phone, plan selection |
| Razorpay subscription creation | ⬜ | `onboarding_service.py` |
| Vobiz DID provisioning via Partner API | ⬜ | `vobiz_partner.py` |
| WhatsApp webhook setup | ⬜ | |
| Google Calendar auto-setup | ⬜ | |
| Welcome WhatsApp message to owner | ⬜ | |
| Trial expiry + payment link automation | ⬜ | Day 12 and Day 14 jobs |
| Free Trial flow (14 days, 1,000 min, no CC) | ⬜ | |

**Exit criteria:** Sign up → go live with zero manual steps from Vinay.

---

## Phase 5 — Production Deploy

**Goal:** Everything running on production infra, monitored, stable.

| Task | Status | Notes |
|---|---|---|
| Deploy voice agent to Fly.io bom | ⬜ | `infra/fly.agent.toml` |
| Deploy backend to Render | ⬜ | `infra/render.yaml` |
| Deploy frontend to Cloudflare Pages | ⬜ | |
| UptimeRobot: monitor all 3 services | ⬜ | SMS alert on downtime |
| Twilio SIP backup configured | ⬜ | Failover from Vobiz |
| Load test: 10 concurrent calls | ⬜ | |
| First real clinic onboarded | ⬜ | 🎯 |

---

## Key Design Decisions Log

Decisions made during brainstorming that future Claude must know:

| # | Decision | Reason |
|---|---|---|
| 1 | Gemini 2.5 Flash = primary LLM (not GPT-4o mini) | Better Telugu language performance |
| 2 | Clinic plan = ₹7,999, 2,100 min (not ₹5,999, 800 min) | 800 min was way too low for 20 calls/day |
| 3 | Multi plan = ₹16,999, 4,200 min (not ₹11,999, 2,000 min) | Same reason — 2 DIDs × 20 calls/day |
| 4 | Emergency MVP = no TYPE_1/TYPE_2, just give emergency_contact | Simpler, avoids liability, good enough for v1 |
| 5 | Anniversary billing (not 1st of month) | Fairer to clinics joining mid-month |
| 6 | No GST for now | Simpler launch |
| 7 | Redis INCR for BOTH token and appointment slot booking | Atomic, prevents double-booking. DECR = rollback only |
| 8 | Doctor-level booking_type (not clinic-level) | Same clinic can have token + appointment doctors |
| 9 | Availability as ranges not individual slots | "2 PM to 6 PM" not "2:00, 2:30, 3:00..." — more natural |
| 10 | Walk-ins get regular token/slot — no special treatment | Simplicity, same Redis INCR |
| 11 | Patient MUST specify day for availability check | Agent never picks a day for patient |
| 12 | Unknown symptom → is_default_doctor (general physician) | Simpler than failing |
| 13 | APScheduler with Redis leader lock (not --workers 1) | More robust, survives restarts |
| 14 | EOD patient context in Redis (36h TTL) for follow-up | Scoped lookup, no full DB search |
| 15 | No-shows dashboard: count only, no revenue estimates | Vinay's explicit preference |
| 16 | Free mins KPI: show REMAINING count (not used) | Vinay's explicit preference |
| 17 | WhatsApp branch = `to_phone` not `from_phone` | Correct branch isolation |
| 18 | Follow-up consent collected during booking call | TRAI compliance |
| 19 | Calendar failure = booking failure | Data integrity — no ghost bookings |
| 20 | WhatsApp failure = notification failure only | Never block the booking |
| 21 | Day cancellation = call + WhatsApp ALL patients with phone | Cancellation is service notification, no consent gate |
| 22 | Day cancellation call retry = 2 attempts, 1h apart (not 3 like follow-up) | Less urgent, faster resolution |
| 23 | Rebook happens in-call after cancellation notification | Same booking flow continues if patient says YES |
| 24 | Appointment-type cancellation: DECR Redis slot key | Frees the slot for future bookings |
| 25 | tokens.status enum includes cancelled_by_clinic | New status for doctor-initiated cancellations |

---

## What To Build Next

**Start here → Phase 0, Task 1: Project directory structure**

```bash
# Create the exact structure from CLAUDE.md:
mkdir -p agent/prompts agent/services agent/tools
mkdir -p backend/models backend/routers backend/services backend/middleware backend/jobs
mkdir -p frontend/src/api frontend/src/hooks frontend/src/pages frontend/src/components
mkdir -p frontend/public
mkdir -p infra
mkdir -p tests/unit tests/integration tests/edge_cases
touch agent/__init__.py agent/agent.py agent/session_state.py
touch agent/requirements.txt
# ... etc per CLAUDE.md structure
```

Then create `.env` from `.env.example` filling in all 25 vars.

Then run Alembic migrations to create all 9 tables.

**Then Phase 1: Start with `agent/services/tts_sanitizer.py` (simplest, most testable).**
