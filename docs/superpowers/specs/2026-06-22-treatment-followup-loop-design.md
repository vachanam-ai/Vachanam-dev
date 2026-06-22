# Treatment Progress + Follow-up Loop — Design

**Date:** 2026-06-22 · **Author:** Vinay + Claude · **Status:** approved (brainstorming), pending implementation plan

## Goal

Let a clinic record a patient's treatment progress visit-by-visit, and run an
automated, two-way, voice-mediated follow-up loop between the doctor and the
patient: the agent calls the patient to ask the doctor's question and/or book the
next visit, captures the patient's reply, and — when the doctor reads that reply
and writes back — calls again to relay the doctor's advice. The agent is a
**messenger, never an author**: it gives no medical advice, no triage, no
diagnosis (RULE 7).

## Decisions locked in brainstorming

1. **Operational-only private notes.** `steps_performed` / `next_steps` are
   dashboard-only — never spoken to the agent, calendar, or SMS. Keeps the
   product clear of EMR/clinical-record storage (CLAUDE.md scope).
2. **Spoken follow-up content is doctor-authored.** The doctor's question and the
   doctor's advice ARE relayed on the call and the patient's reply IS stored —
   but every word of medical content is authored by the doctor. The agent only
   relays (warmly, in the clinic's language) and records.
3. **Booking call timing:** 9am the day AFTER the doctor saves the visit note.
4. **Booking window:** the agent books within **±2 days** of the doctor's
   `next_reporting_date`.
5. **Close treatment:** a "Mark complete" button OR the word `end` in
   `next_steps`. On completion, pending follow-up calls are cancelled.
6. **Advice-relay timing:** as soon as possible after the doctor writes it, but
   only within calling hours (09:00–20:00 IST).

## Non-goals

- No EMR/EHR clinical records (operational notes + doctor-authored messages only).
- No agent-composed medical advice, triage, or diagnosis; no "108"; human
  transfer stays intent-based to the clinic's own emergency contact.
- No WhatsApp/SMS (MVP1 is voice; WhatsApp is MVP2).
- No explicit `TreatmentCourse` entity yet (course is derived; add later if
  concurrent courses per patient are ever needed).

## Hard constraints honoured

- **RULE 1 (tenant isolation):** every table + query is `branch_id`-scoped;
  super_admin is locked out of these routes.
- **RULE 2 (no double-booking):** the agent books via the existing atomic Redis
  token-assign path; never derives a token from a count.
- **RULE 6 (TTS sanitisation):** doctor messages go to the LLM as *context*, not
  raw to TTS; the agent phrases them in the clinic's language.
- **RULE 7 (no agent medical judgment):** agent relays doctor content verbatim,
  composes none of its own; on any reported problem it says it will inform the
  doctor.
- **RULE 9 (PII/health discipline):** notes, doctor advice, and patient feedback
  are health-adjacent → `branch_id`-scoped, erased with the patient by the
  `data_retention` job, never in calendar/SMS; spoken only on the consented call
  (standard DPDP s.5 disclosure recorded as today).

---

## Architecture overview

```
Doctor saves visit note (steps, next steps, next reporting date, optional question)
        │  enqueue FollowupTask(next_visit_book, scheduled_date = visit_date+1)
        ▼  followup_caller job, 9am
[Call] agent asks the doctor's question warmly + offers to book ±2 days
        │  patient reports a problem
        ▼
agent: "I'll inform the doctor; they'll get back to you soon"  → save reply
        │
        ▼  doctor reads reply in dashboard → writes advice (any language)
        │  enqueue FollowupTask(doctor_advice)  → fires ASAP within calling hours
[Call] agent relays the doctor's advice verbatim; asks for more concerns / booking
        │  → save reply
        └─► repeat until doctor marks resolved / treatment is completed
```

The "treatment course" and the "follow-up thread" are both **derived**, not new
top-level entities:
- **Course** = the ordered `treatment_notes` for a patient+doctor up to the one
  with `is_final = true`.
- **Thread** = the ordered `FollowupTask`s linked to a patient (via
  `treatment_note_id`), each carrying one outbound message (`what_to_ask`) and
  the captured reply (`response_summary`).

---

## Data model

### New table `treatment_notes` (one row per visit)

| column | type | notes |
|---|---|---|
| `id` | UUID pk | |
| `branch_id` | FK→branches RESTRICT, idx | RULE 1 |
| `doctor_id` | FK→doctors RESTRICT, idx | |
| `patient_id` | FK→patients RESTRICT, idx | |
| `token_id` | FK→tokens RESTRICT, nullable | the visit this note belongs to |
| `visit_date` | Date, not null | the day treated |
| `steps_performed` | Text, nullable | **dashboard-only**, never spoken |
| `next_steps` | Text, nullable | dashboard-only; `end` here closes treatment |
| `next_reporting_date` | Date, nullable | drives the 9am booking call |
| `is_final` | Bool, default false | set by button OR `next_steps`≈`end` |
| `created_by_user_id` | FK→users, nullable | who wrote it |
| `created_at` / `updated_at` | timestamptz | |

Indexes: `(branch_id, patient_id, visit_date)` (timeline); `(branch_id, doctor_id)` (dropdown).

### Extend `FollowupTask` (reuse for the thread)

Existing fields reused: `what_to_ask` (clinic→patient message), `response_summary`
(patient→clinic reply), `scheduled_date`, `status`, `attempt_count`,
`max_attempts`, `channel='voice'`, `task_type`.

Add:
- `treatment_note_id` UUID FK→treatment_notes RESTRICT, **nullable**, idx — links
  the task into a note's thread.
- `created_by_user_id` UUID FK→users, nullable — which doctor/receptionist
  authored the outbound message.

`task_type` gains two app-side values (VARCHAR, no DB enum change):
`next_visit_book`, `doctor_advice`.

### Migration

One additive Alembic migration (`treatment_notes` + the two `FollowupTask`
columns). Forward-additive, so it runs safely on the prod DB despite the broken
upgrade-from-base chain (see memory `project-alembic-chain-broken`). New DBs are
provisioned via `create_all` + stamp head (existing pattern).

### Retention

Extend `backend/jobs/data_retention.py` so that when a patient is anonymised, its
`treatment_notes` rows (and the health-bearing `what_to_ask`/`response_summary`
text on its `FollowupTask`s) are wiped, consistent with the existing PII erasure.

---

## API (new router `backend/routers/treatment.py`)

All JWT-auth, `branch_guard`-scoped, **super_admin denied**. Writable by
org_admin / doctor / receptionist.

| method | path | purpose |
|---|---|---|
| `GET` | `/branches/{branch_id}/treatment-patients?doctor_id=&status=active\|all` | the dropdown — branch patients, optionally restricted to those with ≥1 token or treatment_note for `doctor_id`; `status=active` → only patients whose latest note is non-final. Returns `{patient_id, name, phone_last4, doctor, last_visit_date, next_reporting_date, active}`. |
| `GET` | `/patients/{patient_id}/treatment-notes` | visit timeline + derived `treatment_status`. |
| `POST` | `/patients/{patient_id}/treatment-notes` | add a visit note. Body: `token_id?`, `visit_date`, `steps_performed?`, `next_steps?`, `next_reporting_date?`, `followup_question?` (the doctor's spoken question, becomes the first thread task's `what_to_ask` — NOT a column on the note), `is_final?`. Runs completion + enqueue logic. |
| `PATCH` | `/treatment-notes/{id}` | same-day correction. |
| `GET` | `/patients/{patient_id}/followups` | the follow-up thread (tasks: `what_to_ask`, `response_summary`, `task_type`, `status`, timestamps). |
| `POST` | `/patients/{patient_id}/followups` | doctor/receptionist writes a message (initial question or advice reply), any language, optional `next_reporting_date` for re-booking → creates a `FollowupTask` + enqueues a call. |

**Validation (Pydantic):** `visit_date` not in the future; `next_reporting_date ≥
visit_date`; text length caps; `doctor_id`/`patient_id` belong to the caller's
branch.

### Completion + enqueue logic (on POST/PATCH note)

- `is_final = true` if the request set it OR `next_steps.strip().lower() == "end"`.
- If `is_final` → cancel any pending `next_visit_book`/`doctor_advice` tasks for
  that patient+doctor; do not enqueue.
- Else if `next_reporting_date` is set OR a follow-up question was provided →
  upsert one pending `FollowupTask(task_type='next_visit_book',
  treatment_note_id=note.id, scheduled_date = visit_date + 1 day,
  what_to_ask = <doctor's question or null>)`. **Idempotent:** a newer note for
  the same patient+doctor cancels the prior pending task and enqueues fresh
  (never two live booking tasks).

### Doctor reply (POST /followups)

Creates `FollowupTask(task_type='doctor_advice', treatment_note_id,
what_to_ask=<advice>, created_by_user_id, scheduled_date=today)` → picked up ASAP
by the caller job within calling hours. Optional `next_reporting_date` attaches a
re-booking intent to the same call.

---

## The caller job (`backend/jobs/next_visit_followup_caller.py`)

APScheduler, runs every ~15 min during **09:00–20:00 IST**:
- Select pending voice `FollowupTask`s of type `next_visit_book` /`doctor_advice`,
  `branch_id`-scoped, that are due:
  - `next_visit_book`: `scheduled_date ≤ today` AND branch-local time ≥ 09:00.
  - `doctor_advice`: created and not yet attempted (fires on the next tick).
- For each: re-check the treatment isn't completed and the patient still has a
  phone; then dispatch the outbound call via the **existing reminder dispatch
  path** (`create_dispatch`, per-clinic outbound trunk), metadata:
  `call_type` (= task_type), `branch_id`, `outbound_trunk_id`, `phone_number`,
  `patient_name`, `doctor_name`, `doctor_id`, `task_id`, `message` (= what_to_ask),
  and for booking: `target_date` (= next_reporting_date) + `window=2`.
  **Never** include `steps_performed`/`next_steps`.
- Retry semantics: `attempt_count`/`max_attempts` as existing; exhausted →
  `status='unreachable'` + dashboard "needs attention" flag.

Render free-tier sleep (which would freeze this in-process scheduler) is already
mitigated by the Fly-agent keepalive (FIXLOG #148).

---

## Agent flow (`agent/livekit_minimal/agent.py` + prompts)

Two new outbound `call_type`s: `next_visit_book`, `doctor_advice`. Both reuse the
instant-welcome bridge, the strict per-call clinic language, and the existing
booking tools.

**`next_visit_book`** prompt extra:
1. Greet patient by name.
2. If `message` present → ask it warmly (LLM relays/translates into the clinic
   language).
3. If `target_date` present → offer to book within ±2 days; on agreement, use the
   booking tools (check availability around the window, atomic token assign,
   calendar write).
4. Capture the patient's reply.
5. If the patient reports a problem → say *"I'll inform the doctor and they'll get
   back to you as soon as possible"* (NO advice). Close warmly.

**`doctor_advice`** prompt extra:
1. Greet by name; "the doctor reviewed your concern."
2. Relay `message` (the doctor's advice) verbatim, warm, in the clinic language.
3. Ask if the patient has more concerns / wants to book (if `target_date`).
4. Capture the reply.

**On call end:** write the captured reply to `FollowupTask.response_summary`, set
`status='completed'`, and mirror the reply onto the patient thread so the doctor
sees it. A booking made on the call follows the normal booking path (token +
calendar). Metadata→agent **never** carries the private notes (RULE 9).

**Safety:** no advice, no triage, no 108; intent-based human transfer to the
clinic's emergency contact only (existing behaviour).

---

## Frontend (React PWA)

New **Treatments** view (TanStack Query + axios-JWT; roles doctor / receptionist /
org_admin):
- **Patient dropdown** from `/branches/{id}/treatment-patients` (doctor sees own;
  receptionist clinic-wide; `active`-only toggle).
- **Visit timeline** — notes by `visit_date`; status badge Active / Completed.
- **Add visit note** form — visit_date (default today), steps performed, next
  steps, next reporting date (optional), follow-up question (optional), "Mark
  treatment complete" toggle.
- **Follow-up thread** — interleaved questions/replies/advice with status; a
  **"Reply to patient"** box (doctor writes advice → triggers a relay call); a
  **"needs attention"** flag for new feedback or an unreachable patient.

Offline queue not required (MVP decision).

---

## Edge cases

- No patient phone → skip the call, flag in dashboard.
- `next_reporting_date` already past at call time → skip booking, still relay any
  message, flag.
- Treatment completed between enqueue and call → job re-checks latest note,
  doesn't dial.
- Patient already booked near the date → agent's existing caller-context confirms
  instead of double-booking.
- Family (many patients, one phone) → task targets `patient_id`; agent greets
  that patient's name.
- Concurrency → double-booking impossible (atomic Redis token assign, RULE 2).
- Night protection → caller job never dials outside 09:00–20:00.

---

## Testing (money / concurrency / isolation first)

- **Unit:** completion logic (`end` keyword + button); enqueue idempotency (newer
  note cancels prior pending task); Pydantic date validation; calling-hours +
  due-selection logic of the job.
- **Isolation:** treatment + followup endpoints reject cross-branch; super_admin
  blocked (RULE 1).
- **Job:** selects only due pending tasks; skips completed / no-phone / past-date;
  `doctor_advice` fires ASAP within hours, `next_visit_book` at 9am.
- **Agent:** `next_visit_book`/`doctor_advice` book within ±2 days; metadata
  carries **no** private notes (RULE 9 assertion); reply written to
  `response_summary`; "inform the doctor" line on a reported problem; double-book
  guard.
- **Retention:** anonymisation wipes treatment_notes + thread health-text.
- Full suite + FIXLOG ritual per change.

---

## Build order (two milestones, one spec)

- **M1 — Notes & dashboard:** `treatment_notes` + migration + `treatment.py`
  notes endpoints (store + `is_final` completion, **no enqueue yet**) + dropdown +
  timeline + "mark complete" + PWA Treatments view. Independently shippable
  (doctors log visits). The `followup_question` field and the enqueue behaviour
  are **M2** — M1 omits them (no thread/call infra exists yet).
- **M2 — The follow-up call loop:** `FollowupTask` thread extension
  (`treatment_note_id`, `created_by_user_id`) + the note POST's enqueue/cancel
  logic + `/followups` endpoints + `next_visit_followup_caller` job + agent
  `next_visit_book` / `doctor_advice` flows + reply UI + retention extension.

> Note: the enqueue/cancel behaviour described under "Completion + enqueue logic"
> belongs to **M2** — in M1 the note POST only stores fields and sets `is_final`.

The implementation plan should be split along these two milestones.
