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

Repriced 2026-07-11 (Vinay): every plan holds ≥40% gross margin at WORST CASE
(full use of included minutes; cost model ₹3/min + ₹1,500 infra/DID/clinic).
Internal plan keys stay `solo|clinic|multi` (DB enum, Razorpay notes, agent
cap logic); "Starter" is the DISPLAY name for `solo`.

| Plan | Price | Included | Doctors | Languages | Premium |
|---|---|---|---|---|---|
| **Lite** (`lite`) | ₹1,999/mo + ₹5/min | 1 DID, 150 min (≈55 calls) | 1 | all 8 | follow-up loop; 4-min AI call cap |
| **Starter** (`solo`) | ₹5,999/mo + ₹5/min | 1 DID, 700 min (≈250 calls) | 3 | all 8 | follow-up loop; 4-min AI call cap |
| **Clinic** ← most popular | ₹9,999/mo + ₹5/min | 1 DID, 1,500 min (≈540 calls) | 5 | all 8 | voice cloning, WhatsApp, follow-up loop |
| **Multi** | ₹17,999/mo + ₹5/min | 1 DID, 3,000 min (≈1,080 calls) | unlimited | all 8 | own voice per language, WhatsApp |

(2026-07-12, Vinay: Starter doctors 1→3 + all languages on every plan — both
zero-variable-cost levers, margins unchanged.)
(2026-07-15, Vinay: NEW **Lite** ₹1,999 entry plan for low-volume clinics that
still pay a receptionist full salary. It DELIBERATELY does NOT hold the
40%-worst invariant — the per-clinic DID+infra floor is too large a share of
₹1,999. Vinay accepted the tradeoff: ~35% margin at TYPICAL cost + low volume,
overage ₹5/min caps the downside. Follow-up loop is NOW on every plan — split
`PREMIUM_VOICE_PLANS` → `CLONING_PLANS` (clinic/multi) + `FOLLOWUP_PLANS` (all);
cloning + WhatsApp stay Clinic+. plan_type enum gains `lite` (migration gg30).)

Overage ₹5/min on every plan. Extra DID ₹1,999/mo. Extra branch ₹7,999/mo —
each extra branch is provisioned as a full new clinic (own DID, Vobiz
sub-account, trunk, doctors, staff; nothing carries over — RULE 1 isolation).
Market in CALLS, meter in MINUTES. Single source of truth for plan economics
AND feature gates: `backend/services/billing_math.py` (PLANS, PLAN_LANGUAGES,
CLONING_PLANS, FOLLOWUP_PLANS, WHATSAPP_PLANS, TRIAL_MINUTES).

All prices are **exclusive of 18% GST** (shown as "+18% GST"; B2B clinics reclaim
it via input credit). **2026-07-17 LAUNCH OFFER (Vinay — clinic feedback "pricing
too much; keep low until first clients"):** for a clinic's FIRST 3 PAID months —
offer prices at 10-15% worst-case margin (Lite ₹1,799 · Starter ₹3,999 · Clinic
₹6,999 · Multi ₹11,999; Lite is below 10%, accepted), GST NOT added for now
(`GST_WAIVED` in billing_math — flip to restore), voice cloning on EVERY plan
during the window, Lite doctors 1→3. UI shows actual price struck through +
offer price labeled "Offer price — first 3 months". Source of truth:
`billing_math.py` OFFER_PRICES / in_offer_window / effective_price /
cloning_allowed.

Free trial: REMOVED 2026-07-17 (Vinay) — new signups start `paused`; the AI
line answers with the blocked line until the first payment activates. Legacy
trial logic (TRIAL_MINUTES, call_blocked trial branches, trial jobs) stays for
pre-existing trial orgs only.

Cost (VARIABLE only): ~₹2.0/min typical, ₹2.6 worst (Vobiz + Soniox +
smallest.ai + Gemini + LiveKit); pricing assumes ₹3/min for safety, + ₹1,000/mo
per DID. Fixed overhead (servers, salaries) separate, dominates at low volume.
Expected blended gross ≈58% at 60% bucket utilization (≈₹6k profit/clinic/mo).
History: 2026-06-16 model (1,999/9,999/15,999 · 100/1800/3600) replaced 2026-07-11.

---

## TECH STACK (deviate only with a logged reason)

| Layer | Tool |
|---|---|
| STT | Soniox stt-rt-v5 primary (Vinay 2026-07-10, real-time Telugu ~$0.12/hr) → Sarvam Saaras v3 fallback when SONIOX_API_KEY unset |
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
