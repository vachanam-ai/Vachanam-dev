# Vachanam — End-to-End Architecture

> Operational correctness and state-machine rules are canonical in
> [`DETERMINISTIC_EXECUTION_ARCHITECTURE.md`](DETERMINISTIC_EXECUTION_ARCHITECTURE.md).
> Prompts may improve conversation quality but may not override those rules.

**Last verified against the running system:** 2026-08-09 (Fly v282, master `7455071`)

Every region, vendor and cadence below was read out of the deployed
configuration, not from memory. Where this document and the code disagree, the
code is right and this file is a bug.

> **Scope note.** `docs/STATUS.md` is the session entry point — what works,
> what is broken, what is next. This file is the *shape* of the system: what
> the pieces are, how a call becomes a booking, and where every legal
> obligation is actually enforced.

---

## 1. What it is

A patient rings a clinic's normal phone number. An AI receptionist answers in
the clinic's language, works out what they need, finds the right doctor, checks
real availability, assigns a token that cannot collide, writes the appointment
to the doctor's Google Calendar, confirms it out loud, and messages the patient
on WhatsApp. The clinic's staff see it on a dashboard; the owner sees usage and
money on a billing page.

**Deliberately not built:** medical advice, diagnosis, triage, prescriptions,
EMR/EHR storage, insurance claims, patient payments, video consults.

---

## 2. The stack, as deployed

| Layer | Vendor | Region | Notes |
|---|---|---|---|
| Telephony (DID + SIP) | Vobiz | **India** | Per-clinic DID; branch resolved from the dialled number |
| Voice runtime | LiveKit Agents on **Fly.io** | **`bom` (Mumbai)** | 1 machine, `shared-cpu-4x` / 4 GB |
| STT | Soniox `stt-rt-v5` | **Japan** (`stt-rt.jp.soniox.com`) | Sarvam Saaras v3 (India) is the fallback |
| TTS | Soniox `tts-rt-v1` | **Japan** | Telugu is sent as Telugu script |
| LLM | Gemini 2.5 Flash via **Vertex AI** | **`asia-south1` (Mumbai)** | Global endpoint only as fallback |
| Database | **Supabase** Postgres | **`ap-south-1` (Mumbai)** | Neon purged 2026-07-31 — do not reintroduce |
| Cache / token locks | Upstash Redis | **Mumbai** | |
| Backend API | FastAPI on **Render** | **Singapore** | Closest region Render offers to India |
| Frontend | React + Vite PWA on Cloudflare Pages | Global edge | |
| Payments | Razorpay | India | RBI-authorised aggregator |
| WhatsApp | Meta Cloud API | Global | Clinic owns its own WABA |
| Calendar | Google Calendar API v3 | Global | Clinic connects its own calendar |

**Residency summary:** telephony, voice compute, the database, the cache and
the language model are all in India. Speech recognition and synthesis are in
Japan. The API is in Singapore. This is what the privacy policy and DPA now
state — they were corrected on 2026-08-09, having previously claimed the
database was in Singapore and STT was in the United States.

**Latency floor.** Measured over ~25 live PSTN turns: warm turn ≈ 1.0–1.3 s,
dominated by the Soniox endpoint (200 ms guard + ~260 ms Mumbai→Tokyo RTT +
finalize), not by the pipeline. LLM ≈ 500 ms, TTS ≈ 400 ms, both flat. The only
sub-1s lever is a regional STT swap.

---

## 3. A call, end to end

```
patient dials clinic DID
   → Vobiz SIP trunk
   → LiveKit room  (branch resolved from the DIALLED number — RULE 5)
   → Fly agent joins, loads branch context (doctors, hours, FAQ, language)
   → greeting plays from a pre-warmed clip
   ↓
   STT (Soniox JP)  →  LLM (Vertex Mumbai)  →  TTS (Soniox JP)
   ↓
   tool calls: route_to_doctor → check_availability → confirm_booking
   ↓
   Redis INCR assigns the token   (atomic — RULE 2)
   Postgres row written           (advisory lock per slot)
   Google Calendar event written  (part of the booking — RULE 4)
   WhatsApp confirmation queued   (never blocks the booking — RULE 4)
   ↓
   end_call — but only once the work is finished (see §6)
```

### The agent's tools

| Tool | Does |
|---|---|
| `route_to_doctor` | Picks the doctor from the complaint and the roster |
| `check_availability` | Real free/busy against schedule + leave + existing bookings |
| `get_doctor_schedule` | Consulting hours for a named doctor |
| `confirm_booking` | Reserves the token, writes the row, writes the calendar |
| `find_my_bookings` | Existing bookings for the **caller's own** number |
| `reschedule_booking` | Moves a booking atomically — new slot confirmed before old is released |
| `cancel_booking` | Cancels and frees the slot |
| `get_queue_status` | Live token position |
| `verify_caller_identity` | Identity gate before any mutation on an existing booking |
| `log_clinic_question` | Question the AI could not answer → doctor answers → patient is called back |
| `take_message` | Message for the clinic |
| `switch_language` | Rebuilds the pipeline in a new language |
| `followup_visit_declined` | Patient declines a follow-up visit |
| `request_human_transfer` | Intent-based only — never keyword-triggered |
| `end_call` | Hangs up, guarded (§6) |

### Language

One language per call, pinned at the STT (`language_hints_strict`). Auto-detect
is **deliberately off, and this is settled** (Vinay, 2026-08-09).

Strict mode does more than choose a language — it normalises everything into
**one script**. A caller's English "okay" comes back as `ఓకే` on a Telugu call,
so the LLM sees a single consistent representation however code-mixed the
speech was. Since most patients speak Telugu-English mixed, per-token language
detection would return `cancel` (Latin) + `చేయండి` (Telugu) inside one
utterance. That breaks three deterministic guards rather than merely confusing
the model: `_dominant_native_language`'s ≥70 % dominance threshold gets diluted,
the `_caller_authorized_*` predicates fail *intermittently* instead of
consistently, and transliteration and TTS sanitisation both assume a known
script per utterance.

Soniox's token-level LID is therefore unexercised in production — strict mode
disables it. What works well is the switch handoff below, not detection.
Switching happens two ways — the model calling `switch_language`, or
`_handoff_explicit_language` swapping the pipeline directly when the caller
asks. Both then acknowledge in one word and **restate the previous answer** in
the new language, rather than announcing that they can speak it.

A saved per-caller preference is a startup hint only; a caller who speaks a
full sentence in another native script overrides it, but only on ≥4 letters at
≥70 % dominance, and Devanagari additionally needs Hindi-vs-Marathi word
evidence because the script alone cannot separate them.

---

## 4. Outbound calls

Four jobs dial patients. All four claim the number in Redis before dispatching,
so one patient's phone rings once no matter how many jobs come due together.

| Job | Cadence | Purpose |
|---|---|---|
| `pre_appt_reminder` | 60 s | Day-before and 30-minute reminders. Skipped when the booking was made within 60 minutes of the appointment |
| `next_visit_followup_caller` | 5 min | Treatment follow-up — booking nudge, or relaying the doctor's reply |
| `cascade_rebook_caller` | 60 s | Doctor went on leave → rebook the affected patients |
| `question_callback_caller` | 5 min | Deliver the clinic's answer to a question the AI could not answer |

Calling windows are enforced per job (09:00–20:00 IST for nudges, 08:00–22:00
for a doctor-initiated callback the patient is waiting on). Every dispatch is
**dispatch-then-mutate**: the row is only marked done once a worker has
actually joined the room, so a crash mid-dispatch can never mark a call
delivered that never rang.

### Other scheduled work

`calendar_writer` (60 s, retries failed calendar writes) · `call_scoring` ·
`data_retention` (daily 19:00 IST) · `finalize_stale_calls` ·
`vobiz_cdr_sync` · `wa_rating_ask` · `support_sla` · billing renewal and
pending plan changes (6 h).

All jobs are leader-elected with a Postgres advisory lock and gated by
`wake_gate` so an idle system leaves the database asleep.

---

## 5. WhatsApp

The clinic owns its WhatsApp Business Account (Embedded Signup; the clinic pays
Meta). Vachanam sends and receives on the clinic's behalf. Branch is resolved
from the **receiving** number, never the sender's.

- Booking, reschedule and cancel over WhatsApp go through the **same**
  `confirm_booking` as the voice path — one implementation, one set of guards.
- Working memory is the last 10 messages plus any in-progress booking. Not an
  archive; 30-day idle expiry.
- Every reply is forced to **Latin script** in `wa_service.send_text` — one
  chokepoint, not a request in a prompt.
- Message IDs are kept 24 h for idempotency; message text is not.

---

## 6. Where the hard constraints are actually enforced

These are the ten rules from `CLAUDE.md`. Each one names the code that makes it
true, because a rule with no enforcement point is a wish.

| # | Rule | Enforced by |
|---|---|---|
| 1 | **Tenant isolation** (DPDP, criminal liability) | `branch_id` on every query; `Token`/`Patient` reads join on it; IDOR sweep tests across every router; super_admin locked out of clinic PII routes |
| 2 | **No double-booking** | Redis `INCR` for the token; `pg_advisory_xact_lock` per slot in `confirm_booking`; never derived from a DB count |
| 3 | **A held token dies with its call** | Release on teardown and on disconnect |
| 4 | **Calendar is part of the booking; notifications are not** | Calendar write inside the booking transaction path; WhatsApp/SMS wrapped in `try/except` that can never fail the booking |
| 5 | **Branch from the dialled number** | DID → branch at room join; WhatsApp uses the receiving `phone_number_id` |
| 6 | **Nothing reaches TTS unsanitized** | `sanitize_for_tts` — strips markdown/symbols, speaks phone digits singly, and speaks clock times as words |
| 7 | **No medical judgment** | No triage tool exists; transfer is intent-based; the clinic's own emergency contact is surfaced, never 108 |
| 8 | **External calls fail gracefully** | `tenacity` retries; LLM auto-fallback; every notification path fails open |
| 9 | **PII discipline** | Logs carry last-4 and IDs, never names; calendar events carry name + last-4 + token only; audit metadata value-scanned for PII |
| 10 | **Structured logs on every significant event** | `structlog` JSON across call lifecycle, bookings, dispatches, failures |

### The call may not end mid-job

`end_call` refuses while a booking, reschedule or cancellation is unfinished.
Two independent signals, because each covers the other's blind spot:

- `caller_asked_to_*` — intent read from the caller's words. Blind to
  Latin-script Telugu.
- `mutation_in_flight` — set when the agent enters its own mutation tool.
  Indifferent to language.

The patient may hang up whenever they like. The agent may not. Escape hatches
that stop this becoming its own outage: a flat refusal clears every flag,
`abandon_pending_booking` overrides, and the silence watchdog deletes the room
without ever consulting the guard.

**Every way a call can end** is enumerated in
`tests/unit/test_call_termination_paths_aug08.py` and pinned against a reviewed
set — a seventh path fails the suite until someone writes down what it does
about a booking in progress.

---

## 7. Compliance

**The applicable law is the DPDP Act 2023.** HIPAA is US legislation and does
not apply to an Indian clinic serving Indian patients. It becomes relevant only
if Vachanam ever handles data of US patients.

- **Roles.** The clinic is the Data Fiduciary; Vachanam is the Data Processor,
  acting on the clinic's documented instructions under a signed DPA.
- **Consent.** Follow-up calls are consent-based and the flag is honoured at
  dispatch time — `followup_consent = False` genuinely stops the phone ringing.
- **Retention.** Identity 2 years after last visit; transcripts 90 days, phone
  numbers masked before storage; Redis booking keys expire same-day; WhatsApp
  working memory 30 days idle. Enforced by the `data_retention` job, not by
  policy prose.
- **Rights.** Access, correction and erasure via `/data-deletion` and
  `patient_erasure`; erasure clears name/phone/age/gender and stamps
  `anonymized_at`, leaving anonymised booking rows for aggregate analytics.
- **Audit.** `audit_log` on privileged actions, with a value-level PII scan on
  metadata.
- **No recording.** Audio is processed in real time and discarded. There is a
  testing-only env-gated override which **must be off before the first paying
  clinic**.
- **No training on patient data.** Enterprise API terms across the LLM
  providers prohibit it.
- **Sector note.** Healthcare is one of five sectors where the Centre may add
  localisation requirements, and the National Health Authority sets its own
  rules for health data. The DPDP Act imposes no unconditional localisation
  today. Vachanam's India-region choices for DB, LLM, cache, telephony and
  voice compute mean a future localisation rule would affect only STT/TTS
  (Japan) and the API host (Singapore).

Published documents: `docs/legal/privacy-policy.md`,
`data-processing-agreement.md`, `terms-of-service.md`, `refund-policy.md`,
`data-handling.md`, `data-deletion.md` — served from `backend/routers/legal.py`.

---

## 8. Known risks

| Risk | Status |
|---|---|
| **Single Fly machine** | One machine in `bom`. A pool-death outage on 2026-07-20 took the line down ~1 h. A watchdog now auto-restarts on ≥3 pool-init errors, but there is still no second machine |
| **Supabase / Section 69A** | `*.supabase.co` was DNS-blocked at Indian ISPs 24 Feb – 4 Mar 2026 under an IT Act s.69A order. Our project is `ap-south-1` and the backend reaches it from Render (Singapore), so the product path is not via Indian ISP DNS — but the precedent is a real concentration risk |
| **Meta token** | A permanent access token was exposed and **still needs rotating** |
| **`wa_waba_id` NULL** | No WhatsApp template can send until one inbound message backfills it |
| **Plan minute cap** | The 4-minute cap on Lite/Starter can cut a booking mid-flow. It warns 10 s ahead. Deliberate — it is a billing limit |
| **Reschedule authorization** | Reschedule has no deterministic authorization gate as of 2026-08-09; only a flat "no" stops it. Chosen because the gate blocked real requests far more often than it caught wrong ones |
| **Stale local `master`** | Holds 50+ unpushed old commits and is missing live ones. Deploy from `restore/v1.12.1` via `git push origin HEAD:master`, gated on an empty `git log HEAD..origin/master` |

---

## 9. Testing

~2,285 tests. The ones that matter are the ones guarding money, concurrency and
isolation: cross-tenant IDOR sweeps, concurrent slot booking (N callers → 1
winner), token collision, billing metering, consent gates, call-termination
paths. CI runs pytest + ruff + gitleaks + frontend build, then tags and deploys
to Fly.

`TZ=Asia/Kolkata` is required — eight date tests fail between 18:30 and 24:00
UTC without it.
