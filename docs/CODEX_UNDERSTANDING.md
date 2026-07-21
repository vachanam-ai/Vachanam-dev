# Vachanam: Codex Codebase Understanding

Last audited: 2026-07-20  
Repository state audited: `master`, HEAD `3d51e12`  
Current Alembic head: `ii32_audit_security`

This is a working reference for future Codex sessions. It summarizes the
current repo as read from source files, not only from older planning docs.

## How To Read This Repo

Priority of truth when sources disagree:

1. Current executable source and tests.
2. `CLAUDE.md` for product law and non-negotiable engineering rules.
3. The top dated block of `docs/STATUS.md` for current state.
4. `docs/TECH_DEBT.md` for known traps and accepted shortcuts.
5. Older phase docs and `docs/PROJECT_STRUCTURE.md` only as history. They are
   useful, but several parts are stale because the product moved quickly.

Files intentionally not treated as behavioral source: `.env`, local secrets,
cache folders, dependency folders, git internals, and binary/audio/image assets
except where they explain product behavior.

## Product In One Sentence

Vachanam is an AI receptionist for Indian clinics. A patient calls a clinic DID,
the LiveKit voice agent answers in the clinic language, identifies intent,
routes to a doctor, checks availability, atomically books a token or slot,
writes calendar state when required, and lets clinic staff manage queue,
treatments, settings, support, billing, and admin views from the PWA.

## Non-Negotiable Invariants

- Tenant isolation: every clinic/patient path must be scoped by `branch_id` or
  `org_id` as appropriate. Super-admin/support surfaces must not casually cross
  into patient PII.
- Branch identity for calls and WhatsApp comes from the receiving clinic number
  or DID, not from the caller/sender number.
- Token assignment must remain atomic. Do not replace Redis counter or slot hold
  logic with count-based "next number" logic.
- Held tokens/slots must be released or naturally expire if a call dies before
  confirmation.
- Calendar behavior is entry-path-specific: voice confirmation currently treats
  it as part of appointment confirmation, while a desk walk-in commits first and
  degrades Calendar failure to durable retry. Notifications are best-effort.
- No medical advice, diagnosis, triage, prescriptions, or emergency-number
  invention. Transfers are intent-based and clinic-scoped.
- Nothing should reach TTS unsanitized. Phone numbers/dates/times need spoken
  handling, not raw symbols.
- Logs and audit metadata must not contain patient names, full phones, or health
  complaints unless a file explicitly documents a compliant reason.
- External systems must fail gracefully. A caller should hear a next step, not
  dead air or a stack trace.

## Runtime Architecture

### Backend API

Entrypoint: `backend/main.py`

- FastAPI app with exact-origin CORS, security headers, prod-hidden docs, public
  legal/static pages, and health diagnostics.
- Lifespan initializes Redis rate limiting and an in-process APScheduler.
- Scheduler leader election uses a Postgres advisory lock so multiple workers
  do not double-dispatch jobs. It uses a session lock (`0x7661636861`), retries
  leadership every 60 seconds during rolling deploys, and explicitly unlocks on
  shutdown.
- Jobs include Calendar retry (60 seconds), pre-appointment reminders (60
  seconds), cascade rebook (60 seconds), next-visit follow-ups (5 minutes),
  WhatsApp rating asks (19:00 IST), trial/billing work (6 hours), data retention
  (24 hours), hourly maintenance and deep checks, a 60-second heartbeat
  watchdog, and optional Render keepalive.

Backend foundation:

- `backend/config.py`: typed environment settings and safety properties.
- `backend/database.py`: async SQLAlchemy; loop-aware engine factory because the
  LiveKit worker can create new event loops per call. Normal pooling is 10 plus
  20 overflow connections.
- `backend/models/schema.py`: single ORM source for organizations, branches,
  doctors, patients, tokens, call logs/quality, calendar tasks, treatment notes,
  follow-ups, billing cycles, WhatsApp state, support tickets/messages, audit
  logs, ratings, consent, doctor unavailability, and patient messages.
- `backend/redis_client.py`: shared event-loop Redis client used where per-call
  client leakage was a previous issue.

### Voice Agent

Entrypoint: `agent/livekit_minimal/agent.py`

- LiveKit Agents worker named `vachanam-agent`.
- STT: Soniox primary when configured; Sarvam fallback.
- TTS: smallest.ai Waves via LiveKit plugin and raw REST for instant greeting
  / cached filler paths.
- LLM: Vertex Gemini 2.5 Flash when service-account credentials are present,
  then global Gemini 3.1 Flash Lite and Gemini 2.5 Flash fallbacks. The current
  voice path does not use an OpenAI fallback despite older documentation.
- Language: branch language plus caller-level preferred language mapping. The
  source supports Telugu, English, Hindi, Tamil, Kannada, Malayalam, Marathi,
  Bengali, and Odia (nine languages, not the older eight-language claim).
- The agent prewarms VAD, LLM, and CalendarService; sends Redis heartbeat only
  after LiveKit registration is detected.
- It has call caps, silence detection, lost-connection handling, language switch
  tools, interruption protection around mutation tools, and Render keepalive.

Agent business logic:

- `agent/prompts/system_prompt.py`: large behavior contract. It is intentionally
  defensive because many real-call failures are encoded as prompt constraints.
- `agent/tools/booking_tools.py`: core booking tools and data guards.
- `agent/livekit_minimal/greeting.py`: inbound/outbound greeting composition,
  TTS synth, raw audio playback, peak normalization.
- `agent/i18n/*`: supported languages, fixed spoken lines, transliteration, and
  backchannel suppression.
- `agent/services/tts_sanitizer.py`: hard TTS cleanup and digit/time rewriting.

### Frontend PWA

Entrypoints: `frontend/src/main.jsx`, `frontend/src/App.jsx`

- React 18 + Vite + React Router + React Query + Tailwind.
- Public routes: landing, login, register, help, TV display.
- Authenticated shell routes are role-gated:
- receptionist: queue, walk-in, treatments, patients, availability, tickets
  - doctor: schedule, queue, treatments, tickets
  - org_admin: dashboard, settings, doctor schedule, queue, walk-in, patients,
    availability, treatments, tickets
  - super_admin: admin, monitoring, support admin
  - support: support admin
- `frontend/src/api/client.js` is the broad API client; `api/support.js`,
  `api/treatment.js`, and `api/patients.js` split newer domains.
- JWT is stored in localStorage. Server logout revokes its JTI, password reset
  bumps `User.token_version`, and protected requests reject deleted users or a
  mismatched token version. LocalStorage remains security debt; do not add more
  sensitive client-side storage.

### Data And Migrations

ORM source: `backend/models/schema.py`

There are 22 current ORM models. Tests create/drop the ORM schema directly
under a PostgreSQL session advisory lock; that path still does not replace a
fresh Alembic-chain upgrade test.

Important entities:

- `Organization`: subscription plan/status, billing identity, GSTIN, pending
  plan changes, minute adjustments, hard block setting.
- `Branch`: tenant runtime scope; DID/WhatsApp/telephony/calendar/language/voice
  settings; FAQ; cloned voices.
- `Doctor`: booking type (`token` or `appointment`), schedule, routing keywords,
  calendar, user account link, weekday availability, walk-in closure.
- `Patient`: branch-scoped PII, primary phone owner, preferred language,
  anonymization marker.
- `Token`: booking record with status, token number or appointment time,
  calendar event id, reminder flags, cancellation metadata.
- `CallLog` and `CallQuality`: metering and quality/judge pipeline.
- `TreatmentNote`, `FollowupTask`, `PatientMessage`: doctor workflow and
  follow-up loop.
- `CalendarWriteTask`: durable async calendar retry queue.
- `SupportTicket`, `SupportMessage`: Vachanam support system, org-level not
  branch-patient data.
- `AuditLog`: no FKs by design; intended append-only.

Migration warning:

- There is documented debt in `docs/TECH_DEBT.md`: the early Alembic chain has
  a from-base collision around `8559268c0c44` recreating tables. Existing prod
  was bootstrapped with `create_all` and stamped, then later migrations applied.
  Until this is fixed, do not assume `alembic upgrade head` from an empty DB is
  safe without checking the current migration-chain tests.

## Key Flows

### Clinic Signup And Login

Files:

- `backend/routers/auth.py`
- `backend/services/otp_service.py`
- `backend/services/validators.py`
- `frontend/src/pages/Register.jsx`
- `frontend/src/pages/Login.jsx`
- `frontend/src/hooks/useAuth.jsx`

Flow:

1. Public auth routes are rate-limited and Turnstile-protected where applicable.
2. Signup accepts email+password+email OTP or Google ID token.
3. New org is created with one branch and org_admin user.
4. Founding trial slots can create `trial` orgs; otherwise new orgs start
   `paused` until first payment.
5. JWT carries role/org/branch access, JTI, and token version. Protected
   dependencies revalidate versioned sessions against the live user row.

### Voice Booking

Files:

- `agent/livekit_minimal/agent.py`
- `agent/prompts/system_prompt.py`
- `agent/tools/booking_tools.py`
- `backend/services/calendar_service.py`
- `backend/services/booking_calendar.py`
- `backend/services/meta_service.py`

Flow:

1. LiveKit dispatch starts the agent with SIP metadata.
2. Dialed DID resolves the branch. This must stay the tenant source.
3. Branch config, doctors, plan, language, FAQ, caller history, preferred
   language, and service gate are loaded.
4. Greeting and disclosure are spoken; consent row is best-effort recorded.
5. The LLM uses tools for routing, availability, assignment, confirmation,
   reschedule/cancel, queue status, language switch, and support handoff.
6. `assign_token` creates a Redis hold/counter; `confirm_booking` revalidates
   identity, duplicates, clashes, and capacity before persisting. Voice slot
   confirmation performs bounded Calendar work before the transaction commits.
7. WhatsApp/notification side effects are fire-and-forget.
8. Shutdown releases unconfirmed holds and finalizes call state where enabled.

Where bugs usually live:

- Prompt says the right thing but the tool wrapper did not expose enough data.
- The LLM skips a mandated step, so `confirm_booking` must keep hard backstops.
- Same-day timezone bugs if code uses server date instead of branch date.
- Token doctors and appointment doctors must not be mixed. Token doctors get
  queue numbers, not clock times.
- Family bookings need `different_person=true` and phone readback rules.

### Receptionist Queue And Walk-Ins

Files:

- `backend/routers/queue.py`
- `frontend/src/pages/Queue.jsx`
- `frontend/src/pages/WalkIn.jsx`
- `frontend/src/pages/TvDisplay.jsx`

Flow:

- Queue reads today in branch timezone, scoped by branch.
- Attend/no-show updates token status and creates a treatment note on attended.
- Public TV display exposes only clinic name, doctors, token numbers, and counts.
- Walk-in uses the same `assign_token` logic as voice. It commits the booking
  before the hybrid Calendar service: appointment Calendar writes retry inline
  at 0, 2, and 5 seconds, then enqueue a durable task; token doctors skip
  per-patient events. Calendar failure never rolls back the desk booking.
- Urgent walk-ins may bypass a full token capacity by current product decision,
  but they never bypass an occupied appointment slot.

### Doctor, Availability, And Cascading Rebook

Files:

- `backend/routers/doctors.py`
- `backend/routers/availability.py`
- `backend/services/cascade_cancel.py`
- `backend/jobs/cascade_rebook_caller.py`
- `frontend/src/pages/DoctorSchedule.jsx`
- `frontend/src/pages/Availability.jsx`

Flow:

- Owners manage doctor schedule, booking type, calendar id, and doctor login.
- Receptionist/owner can mark doctor unavailability.
- Marking leave cancels affected confirmed tokens and enqueues rebook follow-up
  work.
- Outbound call dispatches use branch telephony and LiveKit config.

### Treatment And Follow-Up Loop

Files:

- `backend/routers/treatment.py`
- `backend/services/treatment_logic.py`
- `backend/services/treatment_followup.py`
- `backend/jobs/next_visit_followup_caller.py`
- `frontend/src/pages/Treatments.jsx`
- `frontend/src/api/treatment.js`

Flow:

- Attended bookings open treatment threads.
- Doctors/staff create notes with next steps and optional reporting dates.
- Follow-up tasks can represent next-visit booking or doctor advice.
- Scheduled job dispatches calls inside allowed hours and writes back response
  summaries.
- Patient messages are also surfaced as unread thread items.

### Billing And Plans

Files:

- `backend/services/billing_math.py`
- `backend/routers/payments.py`
- `backend/jobs/trial_pause.py`
- `backend/services/invoice_email.py`
- `frontend/src/pages/Settings.jsx`
- `frontend/src/pages/Landing.jsx`

Current plan keys:

- `lite`
- `solo` displayed as Starter
- `clinic`
- `multi`

Flow:

- UI asks backend to create a Razorpay order for a plan.
- Backend derives amount, including overage and offer pricing; client never
  controls price.
- Verify-payment path and webhook both activate idempotently by payment id;
  payment IDs are database-unique and activation is transaction-serialized.
- Billing cycles are anniversary-based.
- GSTIN is optional; invoice text changes depending on env.

Watch for drift:

- Pricing labels exist in backend math, frontend landing/register/settings, legal
  docs, support docs, and static backend page.
- Feature gates for voice cloning, WhatsApp, languages, follow-up, and minutes
  should come from `billing_math.py` or be clearly derived from it.

### WhatsApp MVP2

Files:

- `backend/routers/whatsapp_webhook.py`
- `backend/services/wa_service.py`
- `backend/services/wa_templates.py`
- `backend/services/wa_actions.py`
- `backend/services/wa_chat.py`
- `backend/jobs/wa_rating_ask.py`
- `backend/services/meta_service.py`
- `docs/runbooks/META_WHATSAPP_SETUP.md`
- `docs/runbooks/META_TEMPLATES.md`

Flow:

- Meta webhook verifies token/signature.
- Receiving phone number id maps to branch.
- Redis dedupe prevents repeated message handling.
- Buttons handle ratings and change/cancel requests; some flows create
  dashboard patient messages instead of self-service booking mutation.
- Free text is answered through the support/FAQ-style guarded AI path.

Important: every WhatsApp send and inbound action is centrally gated by Meta
credentials, branch linkage, and Clinic/Multi entitlement. It no-ops safely
when any gate is absent.

### Support System

Files:

- `backend/routers/support.py`
- `backend/services/support_bot.py`
- `backend/services/support_kb.py`
- `backend/services/support_email.py`
- `backend/services/support_macros.py`
- `backend/jobs/support_sla.py`
- `frontend/src/pages/Help.jsx`
- `frontend/src/components/SupportWidget.jsx`
- `frontend/src/pages/MyTickets.jsx`
- `frontend/src/pages/SupportAdmin.jsx`
- `docs/support/*.md`

Flow:

- Public/in-app KB and chatbot answer from docs.
- One ticket can be created per chat when unresolved or contact/demo submitted.
- Clinic users can read/reply/rate their tickets.
- Support/super_admin staff can list, reply, patch status/priority, and manage
  support staff.
- This domain is org/support scoped; do not mix it with patient PII routes.

### Admin, Monitoring, And Watchdog

Files:

- `backend/routers/admin.py`
- `backend/watchdog.py`
- `backend/services/resilience.py`
- `backend/jobs/maintenance.py`
- `frontend/src/pages/Admin.jsx`
- `frontend/src/pages/Monitoring.jsx`

Flow:

- Super-admin can view owners/clients/business overview, change org state/plan,
  adjust minutes, set hard block, delete orgs, view monitoring, and control
  chaos/resilience board.
- Watchdog monitors voice-plane heartbeat, Redis, memory, DB/deep checks, and
  can restart the Fly agent if configured.
- Chaos harness is hard-off unless `CHAOS_ENABLED=true`.

## Source-Audited Voice and Booking Mechanics

### Call startup and reliability

- Inbound branch resolution uses SIP `sip.trunkPhoneNumber`. A fallback is
  accepted only when exactly one branch exists; ambiguous multi-tenant fallback
  is refused.
- Outbound dispatch metadata distinguishes reminder, cascade-rebook,
  next-visit, and doctor-advice calls and uses per-branch trunks where present.
- Service gate, caller history/follow-up, preferred language, and doctor roster
  are loaded concurrently. Doctor roster and timings are cached per clinic in
  Redis.
- Greeting synthesis/playback overlaps session startup and is seeded into chat
  context. Consent persistence is best-effort.
- STT is Soniox `stt-rt-v5` when configured, with strict language/context bias;
  Sarvam Saaras v3 is fallback. TTS is smallest.ai Lightning, primarily over a
  streaming WebSocket, with a REST/WAV path for greetings and fillers.
- The LLM classifies untrusted complaint text for intent routing, then validates
  any returned doctor ID against the current branch roster. It is not allowed to
  diagnose, triage, prescribe, or invent emergency guidance.
- `SessionState` is per call and owns branch, doctor, patient, active holds,
  confirmations, follow-up state, family-member count, quality, and call-log
  state. Call-scoped mutable data must not move into module globals.
- Mutating tools are pinned against ordinary interruption. The worker also has
  echo/backchannel filtering, strict language handoff, silence checks around 10
  and 20 seconds, hangup around 30 seconds, and repeated-hello lost-line logic.
- Current Starter/Solo default cap is 600 seconds and is configurable; the
  absolute cap for other calls is 900 seconds. Older four-minute documentation
  is stale.
- Heartbeat is written only after LiveKit registration is detected. The API
  watchdog considers roughly 180 seconds without heartbeat stale.

### Tools exposed to the voice model

The live agent can route to a doctor, check availability, assign a token/slot
hold, confirm a booking, find existing bookings, report queue state, reschedule,
cancel, log a clinic question, take a patient message, record a declined
follow-up, switch language, request a human transfer, and end the call. Prompt
instructions are not the integrity boundary: the tools must retain validation
and authorization backstops.

### Token doctor algorithm

1. Redis Lua floors the sequence against confirmed database state and atomically
   increments `token:doctor:branch:date`.
2. The minted number is monotonic and never reused or decremented.
3. Capacity is based on confirmed seats, not the sequence's high-water mark, so
   cancellation can free capacity without reusing a number.
4. Expiry is tied to branch-local midnight plus a safety window.

### Appointment doctor algorithm

1. Date, schedule, grid, past-time, leave, and capacity are validated.
2. Redis key `slot:doctor:branch:date:HHMM` creates a 15-minute hold.
3. Confirmed database occupancy is a backstop.
4. Final confirmation uses a Postgres advisory transaction lock for the slot.
5. Confirmation normalizes Indian mobile numbers and rechecks patient identity,
   same-doctor/day duplicates, cross-doctor time clashes, and capacity.
6. Reschedule confirms the replacement before cancelling the old booking.
   Cancel releases appointment occupancy but never decrements token sequence.
7. Unconfirmed holds are released during exception/shutdown paths or expire.

### Calendar policy seam

The source has two real policies and future work must identify the entry path:

- Voice appointment confirmation treats Calendar creation as part of the
  confirmation operation. Bounded Calendar failure rolls back/releases the
  uncommitted confirmation. Token doctors have no per-patient Calendar event.
- Desk walk-in first commits a confirmed booking. For appointment doctors,
  `write_booking_calendar` tries inline at 0, 2, and 5 seconds. Exhaustion writes
  `CalendarWriteTask(status='pending')`; missing configuration writes
  `failed_permanent` and alerts admins. Neither reverses the desk booking.

Calendar cancellation is best-effort/time-bounded. Never include complaint text
in Calendar fields; the implementation limits identity to first name and masked
phone suffix where needed.

## Authentication and Frontend Runtime Details

- JWT is HS256, normally eight hours, and carries `jti`, role, organization,
  branch IDs, and admin state. Redis stores revocation state.
- `org_admin` derives organization branch access from the database;
  receptionist and doctor roles use explicitly assigned branch IDs.
- The SPA stores JWT in `localStorage`, adds it through Axios, and clears it on
  401. This is known security debt; do not add more sensitive browser storage.
- Auth and anonymous support routes use one-use Turnstile tokens where relevant.
  Tokens are request-scoped; each widget resets only when its own token is
  consumed, so simultaneous forms cannot steal each other's challenge.
- Public routes are landing, login, register, help, and queue TV. Protected
  pages are lazy-loaded and role-gated.
- Multi-branch users explicitly choose the active branch in `Shell`. The
  selection is validated against `branch_ids`, persisted per user, and used by
  all branch-scoped pages through `useAuth`.
- Axios has a 15-second timeout. Newer patient, treatment, and support domains
  have separate API modules in addition to the shared client.
- Vite's development proxy covers all active API prefixes, including patients,
  treatment, support, and webhooks.
- Owner-facing WhatsApp setup is controlled at build/runtime by
  `VITE_WHATSAPP_LIVE`; backend gates remain authoritative.

## Billing Authority and Current Plans

`backend/services/billing_math.py` is authoritative for amount and feature
gates. The browser never controls a charge amount.

| Key | Display | Monthly price | Included minutes | Overage | Doctor limit |
|---|---|---:|---:|---:|---:|
| `lite` | Lite | INR 1,999 | 150 | INR 5/min | 3 |
| `solo` | Starter | INR 5,999 | 700 | INR 5/min | 3 |
| `clinic` | Clinic | INR 9,999 | 1,500 | INR 5/min | 5 |
| `multi` | Multi | INR 17,999 | 3,000 | INR 5/min | unlimited |

Launch-offer pricing is removed; standard plan prices are charged. `GST_WAIVED`
is currently true, and invoices omit a zero-tax/18% claim while it is waived.
Trial allowance is 300 minutes and nominal pilot duration is 14 days.

All plans receive supported languages and follow-up. Normal voice-clone access
is Clinic/Multi but expands during the offer window. WhatsApp is Clinic/Multi.
Trials hard-block at allowance; active paid organizations normally accrue
overage unless explicitly hard-blocked.

Current registration can grant trials globally or through a capped founding
allocation. Allocation is serialized with a PostgreSQL advisory lock, and the
landing/login trial claims read the live slot endpoint before advertising it.

Razorpay orders are created server-side from a plan key. Verification and
webhook activation are idempotent by payment ID; cycles are anniversary-based.
Pricing text is duplicated in landing/register/settings, legal/static pages,
and support content, so a price change requires a drift search even though the
backend remains the authority.

## HTTP Domain Map

The application has roughly 70 route handlers:

- App/health: `/`, `/dev/test`, `/health`, plus protected voice-plane,
  rate-limit, and Redis diagnostics.
- Auth: Google, register/login/logout/me, founding slots, account deletion, OTP,
  forgot/reset password.
- Branches: settings, voice/voices, FAQ, clinic questions/messages, ratings,
  cloned voices, telephony, Calendar test, staff.
- Doctors/availability: CRUD, stop-walk-ins, leave CRUD, affected bookings,
  upcoming leave.
- Queue: today, attend, no-show, public display, walk-in.
- Patients: branch patient/upcoming lists and patient edit/delete.
- Treatment: notes, patients, end-treatment, follow-ups, replies, mark-read.
- Analytics: overview and call quality.
- Payments under `/api`: order, plan/change, billing/GSTIN, verification, and
  Razorpay webhook.
- Support: KB/chat/contact; clinic tickets/messages/CSAT; staff console,
  replies/status/macros/users.
- Admin: owners, clients, overview, organization controls, monitoring,
  health/resilience, WhatsApp branch link.
- WhatsApp: Meta GET/POST webhook under `/webhooks/whatsapp`.
- Legal: privacy, terms, refunds, DPA, handling, and data safety.

## WhatsApp Processing Details

Meta POST verifies HMAC, maps the receiving `wa_phone_number_id` to a branch,
and deduplicates message IDs in Redis for 24 hours. After authentication,
handler errors return HTTP 200 to prevent Meta retry storms. Sends require valid
credentials, branch linkage, and a permitted plan.

Ratings accept 1-5 and alert the owner at 2 or below. Change/cancel buttons do
not mutate a booking; they create a `PatientMessage` and tell the patient the
clinic will call. Guarded free-text classification handles reschedule, cancel,
location, FAQ, and out-of-scope intents without medical advice. Missing Meta
configuration is a safe no-op.

## Test Map

Audit-time inventory: 190 Python test files with 1,088 test functions: 95 unit,
70 integration, 22 security, and 3 edge-case files. The frontend has 3 test
files.

Test layout:

- `tests/unit/`: business logic, prompt rules, small service behavior, frontend
  component tests.
- `tests/integration/`: route flows, booking, payments, treatment, WhatsApp,
  calendar writer, support, admin, patient records.
- `tests/security/`: CORS, headers, JWT, rate limiting, tenant isolation, RBAC,
  attack sweeps, secrets scan.
- `tests/edge_cases/`: concurrency and isolation edge cases.

Important test harness facts:

- `tests/conftest.py` is intentionally defensive. It has prod fuses and uses
  separate test DB settings.
- Some tests expect real Postgres/Redis semantics; do not silently swap to
  SQLite/fakeredis unless the test explicitly does.
- When changing voice behavior, search tests for the specific real-call bug id
  comments. Many tests encode regressions from production calls.
- When changing pricing, run billing, launch-offer, legal-route, settings, and
  landing/register related tests.
- When changing tenant access, run security IDOR/RBAC tests, not just happy paths.

Verification performed during the audit and remediation:

- `npm run lint`: passed.
- Frontend tests: passed, 3 files / 6 tests.
- Frontend production build: passed, 174 modules; main bundle about 415 KB
  (138 KB gzip) plus lazy route chunks.
- Permanent audit contracts: 51 passed; DB exploit regressions: 5 passed.
- Complete unit suite: 689 passed.
- Complete integration/security suite: 539 passed, 3 intentionally skipped.
  Dedicated rate-limit tests remain un-bypassed.
- Edge-case suite: 6 passed.
- `ruff check backend agent tests alembic`: passed.
- Python compilation for backend and migrations: passed.

## Operational Files

Current deployment topology:

- FastAPI: Render Singapore, native Python free-plan service, one worker.
- Voice worker: Fly.io Mumbai, Python 3.12, 4 shared CPUs / 4 GB, always on,
  rolling deployment, no HTTP service.
- React SPA: Cloudflare static/Workers hosting with SPA fallback.
- Neon Postgres and Upstash Redis.
- Vobiz/LiveKit, Google Calendar, Razorpay, Meta WhatsApp, Resend/SMTP/MSG91,
  and Cloudflare Turnstile integrations.

`render.yaml` has no pre-deploy migration command; migrations are manual. The
API, Fly worker, and GitHub keepalive workflow all participate in keeping the
free Render service warm. `.env.example` currently describes about 71 keys, not
the roughly 26 stated in older documentation. Production recording is forcibly
disabled by config, and OTP echo is non-production only.

- `docker-compose.yml`: local Postgres 16 and Redis 7.
- `infra/Dockerfile.backend`: copies both `backend/` and the required `agent/`
  package used by `backend.main` logging imports.
- `infra/Dockerfile.agent`: LiveKit agent image. Check it before agent dependency
  changes.
- `render.yaml`: Render backend blueprint.
- `infra/fly.agent.toml`: Fly agent deployment.
- `.github/workflows/ci.yml`: CI test path.
- `.github/workflows/security.yml`: security/dependency checks.
- `.github/workflows/keepalive.yml`: external keepalive history; check before
  changing schedulers.

Scripts:

- `scripts/setup_livekit_telephony.py`: global inbound LiveKit telephony setup.
- `scripts/create_vobiz_outbound_trunk.py`: per-clinic outbound trunk creation.
- `scripts/check_vobiz_did_ready.py`: Vobiz DID preflight.
- `scripts/create_super_admin.py`: platform admin provisioning.
- `scripts/seed_phase1.py`: seed local/dev clinic data.
- `scripts/dsar.py`: DPDP export/correct/delete/withdraw CLI.
- `scripts/backfill_clinic_spoken.py`, `scripts/backfill_welcome_audio.py`:
  speech/greeting data backfills.
- Reminder and humanizer scripts are diagnostics/simulation helpers.

## Known Problems And Sharp Edges

- Alembic from-base upgrade is not fully trustworthy due to the documented early
  chain collision. Check migration tests and `TECH_DEBT.md` before touching it.
- There is one current head (`ii32_audit_security_constraints`), but one head does not make
  the broken fresh-base path safe. Normal tests use `create_all` and can miss it.
- The ZAP workflow still runs a fresh `alembic upgrade head` and may expose that
  early-chain debt. ZAP covers master/main PRs and Dependabot targets `master`.
- `google-service-account.json` is present locally and gitignored; long-term
  backlog says move to env/base64 even in dev.
- JWT in localStorage plus CSP looseness is a known low-risk backlog item.
- Any single super_admin can create another super_admin; this is a known
  platform-takeover blast-radius concern.
- Audit log append-only DB permissions need separate prod role setup; schema
  alone does not enforce it.
- Agent deploys can create a LiveKit worker registration gap; `TD-039` calls for
  blue-green deploy with health check before paying clinics.
- Token capacity has subtle distinctions:
  - Token number minting must remain monotonic.
  - Confirmed-seat capacity can free cancelled seats.
  - Slot occupancy has Redis hold plus DB/advisory-lock backstops.
- Do not use caller phone as tenant identity in voice or WhatsApp.
- Do not put health complaint text into calendar summaries, notifications, audit
  metadata, or logs.
- `PROJECT_STRUCTURE.md` is useful but stale about frontend and several backend
  domains. Update it only if asked or as part of repo policy work.
- `docs/GO_LIVE.md` and older deploy notes contain stale migration, auth, and
  worker assumptions; use current manifests and source.
- Some older status/phase documents can still drift from executable pricing,
  language, and trial behavior. Runtime source and the corrected support KB are
  authoritative.
- Calendar failure behavior differs between voice and desk entry points.
- Vobiz subaccount/DID provisioning and credential rotation retain manual steps;
  local-region DID availability is an external operational constraint.
- GSTIN support is not yet a complete statutory invoice sequence/place-of-supply
  implementation.
- Some resilience/breaker state is process-local and scheduled work is coupled
  to the single Render API leader.
- `docs/TECH_DEBT.md` contains duplicated or stale IDs; read current issue text
  and source rather than trusting an identifier alone.

## Where To Patch Common Requests

- Change pricing or plan gates: `backend/services/billing_math.py`, then mirror
  labels in `frontend/src/pages/Landing.jsx`, `Register.jsx`, `Settings.jsx`,
  legal/support docs, and possibly static backend landing.
- Change booking correctness: start in `agent/tools/booking_tools.py`; then adjust
  `agent/livekit_minimal/agent.py` tool wrappers and prompt if the LLM needs new
  behavior.
- Change spoken behavior only: usually `agent/prompts/system_prompt.py` and/or
  `agent/i18n/lines.py`; still check TTS sanitizer.
- Change frontend API wiring: `frontend/src/api/client.js` or the domain-specific
  API module, then the owning page.
- Change queue desk behavior: `backend/routers/queue.py` plus `Queue.jsx` or
  `WalkIn.jsx`.
- Change doctor schedule/leave: `backend/routers/doctors.py`,
  `backend/routers/availability.py`, `backend/services/cascade_cancel.py`,
  `DoctorSchedule.jsx`, `Availability.jsx`.
- Change follow-up/treatment: `backend/routers/treatment.py`,
  `backend/services/treatment_followup.py`, `backend/jobs/next_visit_followup_caller.py`,
  `Treatments.jsx`.
- Change support: `backend/routers/support.py`, `backend/services/support_*`,
  `Help.jsx`, `SupportWidget.jsx`, `MyTickets.jsx`, `SupportAdmin.jsx`.
- Change auth/security: `backend/middleware/auth_middleware.py`,
  `backend/middleware/rate_limit.py`, `backend/services/turnstile.py`,
  `backend/routers/auth.py`, and security tests.
- Change deploy/ops: inspect `render.yaml`, `infra/*`, `.github/workflows/*`,
  and relevant runbook under `docs/runbooks/`.

## Safe Change Routine

Before editing:

1. Search the exact feature name and route/function with `rg`.
2. Read the owning router/service/page and the matching tests.
3. Check `TECH_DEBT.md` if the area involves migrations, auth, payments, voice,
   calendar, or deploy.
4. Preserve branch/org scoping and PII discipline.
5. Add or update a targeted test when touching money, booking, isolation, auth,
   migrations, or voice regressions.

After editing:

1. Run the smallest relevant tests first.
2. For frontend UX changes, run build and inspect the page if a browser is
   available.
3. For backend route changes, run direct route tests and security tests if
   access control changed.
4. For voice changes, run the specific unit/integration tests tied to that bug
   and avoid broad prompt churn unless needed.

## Audit Regression Gates (2026-07-20)

The whole-code audit is recorded in [CODE_AUDIT_FINDINGS.md](CODE_AUDIT_FINDINGS.md).
It adds permanent contracts in `tests/unit/test_code_audit_regressions.py` and
DB-backed exploit regressions in `tests/security/test_code_audit_exploits.py`.
All 43 findings are remediated; treat every `AUDIT-*` case as a security,
correctness, release, or product-truth invariant that must remain green.
