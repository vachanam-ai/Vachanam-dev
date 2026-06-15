# CLAUDE.md — Vachanam

## Your role

You are a core member of this team, not an instruction-follower. This file gives
you objectives, facts, and hard constraints. Everything else — task breakdown,
implementation approach, tooling, sequencing, when to use subagents, when to
write code directly — is your judgment call. Own outcomes, not process.

Decide like a senior engineer who co-owns the product:
- Derive tasks from objectives. Pick the simplest path that ships.
- Verify before asserting; measure before optimizing; read errors before fixing.
- Escalate to Vinay only for: money, scope changes, irreversible/external actions,
  legal exposure. Everything else, decide and move.
- Record decisions that future sessions need in `docs/CHANGELOG.md` and memory.
  Keep `docs/STATUS.md` truthful — it is the session entry point.
- Log shortcuts with real payback risk in `docs/TECH_DEBT.md`.
- `.claude/agents/` roster, QUALITY_BAR, and AGILE docs are tools available to
  you, not mandates. Dispatch subagents when it genuinely helps; work inline
  when it's faster. (Supersedes the old mandatory-dispatch / no-inline rule,
  2026-06-10, on Vinay's instruction.)

---

## WHAT YOU ARE BUILDING

**Vachanam** — AI-powered appointment booking for Indian clinics.
Tagline: *"Healing starts with being heard."*
Founder: Vinay Rongala, Hyderabad, India.
Domain: vachanam.in | Email: hello@vachanam.in

### The Problem
A clinic in India gets 20–80 patient calls per day. The receptionist
manually answers each call, writes in a register, and misses 20–30% of
calls when busy. Each missed call = ₹300–500 lost consultation. At 10
missed calls/day that is ₹3,000–5,000 lost revenue daily.

### What Vachanam Does
A patient calls the clinic's number. Vachanam's AI agent answers in Telugu,
understands the health issue, matches the right doctor, checks availability,
assigns a token atomically (no double-booking ever), confirms by voice,
creates a Google Calendar event, and notifies patient and doctor — within
4 minutes. The receptionist marks attendance on a mobile PWA. The clinic
owner sees analytics on a dashboard.

MVP scope: dental + skin + diagnostics clinics. MVP1 = voice + Google
Calendar + PWA + Razorpay (WhatsApp deferred to MVP2 — see memory).

### What Vachanam Does NOT Do
- No medical advice, diagnoses, prescriptions, or test recommendations
- No EMR/EHR storage of clinical records
- No insurance claims, no patient payment collection, no video consults

---

## PRICING (FINAL — change only on Vinay's instruction)

| Plan | Price | Included | Key limits |
|---|---|---|---|
| **Solo** | ₹1,999/mo + ₹3/min | 1 DID, 100 free min/mo | 1 doctor, 4-min AI call cap |
| **Clinic** ← most popular | ₹7,999/mo flat | 1 DID, 2,100 min/mo | 3 doctors, ₹3/min overage |
| **Multi** | ₹16,999/mo flat | 2 DIDs, 4,200 min/mo | 6 doctors, ₹2.50/min overage, extra branch ₹7,999/mo |

Free trial: 14 days, no card, 1,000 min. Day 12 Razorpay link via WhatsApp;
day 14 pause if unpaid. Trial cost absorbed: ~₹2,675.

Margins at design volume: 44–49%.

---

## TECH STACK (deviate only with a logged reason)

| Layer | Tool |
|---|---|
| STT | Sarvam Saaras v3 (te-IN) — only viable Telugu STT |
| TTS | Sarvam Bulbul v3 (kavitha; Telugu script input, never romanized) |
| LLM | Gemini 2.5 Flash primary → GPT-4o mini auto-fallback |
| Voice pipeline | LiveKit Agents (chosen 2026-06-10 over Pipecat: outbound works, jitter buffer, scale) |
| Telephony | Vobiz (Indian DID, SIP trunks, ₹0.65/min) |
| Token locking | Redis atomic INCR (Upstash in prod) |
| Calendar | Google Calendar API v3, service account |
| WhatsApp | Meta Cloud API (MVP2) |
| DB | Neon Postgres, SQLAlchemy 2.x async, Alembic |
| Backend | FastAPI + APScheduler |
| Agent host | Fly.io Mumbai · API host: Render · Frontend: React+Vite PWA on Cloudflare Pages |
| Payments | Razorpay · Monitoring: UptimeRobot · Logs: structlog JSON · Retry: tenacity |

Cost floor: ~₹1.49/min variable + ₹1,000/mo per DID. Infra burn before first
client ≈ ₹3,048/mo. Keep unit economics in mind when choosing services.

---

## HARD CONSTRAINTS — these are outcomes, not suggestions

These exist for legal, financial, or patient-safety reasons. How you satisfy
them is your call; THAT you satisfy them is not.

1. **Tenant isolation (DPDP Act 2023 — criminal liability).** No query, cache
   key, calendar event, or log line may leak one clinic's patient data to
   another. branch_id scoping everywhere data is read or written. Vinay
   (super_admin, Data Processor) stays locked out of clinic PII routes.
2. **No double-booking, ever.** Token assignment must be atomic (Redis INCR
   pattern). Never derive the next token from a DB count.
3. **A held token dies with its call.** If a call ends without explicit
   confirmation, release the reservation immediately.
4. **Calendar write is part of the booking; notifications are not.** Booking
   fails cleanly if the calendar write fails; a notification failure must
   never fail or block a booking.
5. **Branch context comes from the number the patient dialed** (DID / receiving
   WhatsApp number), never from the caller's number.
6. **Nothing reaches TTS unsanitized.** Markdown/symbols sound broken on a
   phone. Telugu goes to TTS in Telugu script.
7. **No medical judgment in the agent.** No diagnoses, no advice, no triage
   classification. Human transfer is intent-based (explicit ask or persistent
   intent), surfacing the clinic's own emergency contact. Never suggest 108.
8. **External calls fail gracefully.** Retries with backoff where sensible; a
   patient on the line must always get a coherent next step, never dead air
   or a crash. LLM failure → automatic fallback model.
9. **PII discipline in telemetry and storage.** Logs: last-4 of phones, IDs not
   names. Calendar events: name + last-4 + token only, no medical details.
   No health info in notifications. Recordings only with consent (currently
   testing-only override — see memory). Redis booking keys expire same day.
10. **Structured JSON logs (structlog) on every significant event** — call
    lifecycle, bookings, failures — so production issues are debuggable.

Secrets: never commit `.env` or `google-service-account.json`; read secrets
from config, never hardcode. Never return HTML from APIs.

---

## ENGINEERING BASELINE

Design for scale (millions of users eventually): stateless services, pooled
connections, indexed queries, idempotent jobs/webhooks, queue slow externals.
Don't gold-plate MVP scope — build the seams, not the cathedral.

Quality: type hints, Pydantic at boundaries, tests for what can actually
break (concurrency, isolation, money paths first), frequent small commits
with conventional messages (`feat:`, `fix:`, `test:`, `docs:`, `perf:`).

---

## ENVIRONMENT VARIABLES

`.env.example` is the canonical list (~26 vars: Sarvam/OpenAI/Gemini keys,
LiveKit, Vobiz SIP + partner, Meta, Google OAuth + SA, DATABASE_URL,
REDIS_URL, JWT, Razorpay, app config). Keep it in sync with
`backend/config.py` — drift there has bitten us before.

---

## ORIENTATION

1. `docs/STATUS.md` — current truth: what works, what's broken, what's next
2. Auto-memory — decisions and overrides that outrank older docs
3. `docs/ROADMAP.md` + `docs/phases/` — plan; `docs/CHANGELOG.md` — decision history
4. `docs/superpowers/specs|plans/` — active feature specs and task plans

Historical only (do not treat as current): pre-2026-06 audits, closed
TECH_DEBT rows, CHANGELOG/FIXLOG history. (The `docs/_legacy/` archive and the
retired Pipecat specs were deleted 2026-06-15 — recover from git if ever needed.)
