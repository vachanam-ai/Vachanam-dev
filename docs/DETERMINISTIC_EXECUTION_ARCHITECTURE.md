# Vachanam deterministic execution architecture

**Canonical correctness contract — 2026-08-10**

This document defines how Vachanam must behave from ingress to patient reply.
It overrides prompt-only approaches for operational decisions. If code and
this document disagree, the mismatch is a defect and the safer fail-closed
behaviour wins until it is corrected.

## 1. Guarantee boundary

No production system can guarantee that a carrier, speech recogniser, LLM,
calendar provider, database, or patient connection will never fail. Vachanam
can and must guarantee the following even when one of them does fail:

1. A failure never becomes an invented fact.
2. A failed mutation never produces success speech.
3. A successful mutation never produces failure speech.
4. One clinic can never read, change, call, or message another clinic's data.
5. One request can create at most one business mutation.
6. The database, not conversational memory, determines current truth.
7. A stale response from an earlier turn can never be spoken in a later turn.
8. The patient always receives one truthful terminal outcome or one explicit
   recovery step; never contradictory answers or silent abandonment.

The LLM is therefore a **language parser and wording assistant**, not the
booking engine, policy engine, database, authorization system, or source of
truth.

## 2. One execution path for every channel

```text
PSTN / WhatsApp / dashboard
          |
          v
1. Resolve tenant from receiving identity
          |
          v
2. Normalize input + assign interaction_id / turn_id
          |
          v
3. Classify intent and extract candidate fields
          |
          v
4. Validate fields against authoritative database snapshot
          |
          v
5. Build a typed command or typed query
          |
          v
6. Execute exactly once behind authorization + concurrency guards
          |
          v
7. Persist authoritative outcome + audit event + outbox event
          |
          v
8. Render speech/text only from that outcome
          |
          v
9. Deliver optional notifications asynchronously
```

Voice, WhatsApp, and dashboard actions may have different adapters. They must
converge before step 4 and use the same command handlers from step 5 onward.
No channel may maintain a second booking implementation.

## 3. Required request envelope

Every query or mutation carries an immutable envelope:

| Field | Rule |
|---|---|
| `interaction_id` | One call, WhatsApp conversation, or dashboard action |
| `turn_id` | Monotonically increasing within the interaction |
| `command_id` | Idempotency key; stable across retries |
| `branch_id` | Derived from dialled DID / receiving WhatsApp ID / authenticated dashboard branch |
| `actor` | Caller number, WhatsApp sender, or authenticated user ID |
| `channel` | `voice`, `whatsapp`, `dashboard`, or `job` |
| `language` | Explicit current output language |
| `received_at` | Server timestamp, never model-generated |

`branch_id` is immutable. A model tool argument is never allowed to override
it. Patient phone numbers select a patient only inside that branch; they never
select the branch.

## 4. Authority hierarchy

When two sources disagree, this order always wins:

1. Database constraints and committed rows.
2. Transaction-scoped service results.
3. Current branch configuration loaded from the database.
4. Provider-confirmed external state where required (Calendar / Meta).
5. Cache values validated by tenant, version, and expiry.
6. Current-turn structured extraction.
7. Conversation history.
8. Prompt examples or LLM prose.

A lower source can never override a higher source. Cache misses may cost time;
cache disagreement must never change truth.

## 5. Non-negotiable invariants

### Tenant and identity

- All persisted business rows contain `branch_id`.
- Every repository method requires a `BranchScope`; unscoped patient queries
  are forbidden.
- Inbound voice resolves the branch only from the number dialled.
- Inbound WhatsApp resolves the branch only from Meta's receiving
  `phone_number_id` and only while the connection is canonically connected.
- Existing appointments are disclosed only when their booking phone equals
  the normalized caller/sender phone for the same branch.
- Super-admin routes cannot read patient conversation content.

### Facts

- Doctor names, specialties, working sessions, leave, fees, clinic details,
  FAQs, booking state, reminder policy, and queue position come from database
  queries or deterministic policy code.
- “Available” means the availability engine returned an offer for that exact
  doctor, date, session, and time/token under the current snapshot.
- “Booked”, “rescheduled”, or “cancelled” is legal only after the corresponding
  command returned a committed success outcome.
- Unknown medical or clinic-policy questions become a tracked clinic question;
  the model must not complete the missing answer.

### Mutations

- A mutation requires a typed command, explicit authorization, and a stable
  `command_id`.
- Database uniqueness/advisory locks enforce capacity; prompts never do.
- Replaying a command returns its original result and performs no second write.
- Reschedule is one logical transaction: reserve replacement, update calendar,
  commit replacement, then release the old capacity. Failure preserves the old
  confirmed appointment.
- Cancel is idempotent: cancelling an already-cancelled appointment returns the
  same cancelled outcome without another notification.
- Notifications are durable outbox work and never decide mutation success.

### Responses

- Operational responses are rendered from a finite `OutcomeCode`, not freely
  regenerated after tool execution.
- Exactly one terminal outcome is spoken per command.
- Internal instructions, tool JSON, reasoning, trace labels, model control
  tokens, and provider errors are rejected at the TTS/text boundary.
- A turn epoch must still be current before audio is published. Interruption,
  language switch, deterministic response, or a newer turn invalidates all
  older speculative generation.

## 6. Canonical state machines

### 6.1 Voice turn

```text
LISTENING
  -> FINALIZING
  -> INTERPRETING
  -> VALIDATING
  -> EXECUTING (queries may skip this)
  -> RENDERING
  -> SPEAKING
  -> LISTENING
```

Terminal side states are `INTERRUPTED`, `RECOVERABLE_ERROR`, and `ENDED`.
Every transition compares `(interaction_id, turn_id, generation_epoch)`. Audio
whose epoch is no longer current is discarded, even if its provider finishes.

### 6.2 Booking

```text
COLLECTING -> OFFERED -> AWAITING_CONFIRMATION -> COMMITTING -> CONFIRMED
                       \-> DECLINED
                       \-> EXPIRED
COMMITTING             \-> FAILED (no booking exists)
```

An offer contains `doctor_id`, `service_date`, `session_id`, slot/token,
`availability_version`, and expiry. Confirmation of a different or expired
offer returns to validation; it never guesses the patient's intended slot.

### 6.3 Reschedule

```text
ORIGINAL_VERIFIED -> REPLACEMENT_OFFERED -> AWAITING_CONFIRMATION
  -> COMMITTING -> RESCHEDULED
  -> FAILED_WITH_ORIGINAL_PRESERVED
```

The success renderer receives both the old and new committed values. The model
does not remember either one.

### 6.4 Cancellation

```text
BOOKING_VERIFIED -> AWAITING_CONFIRMATION -> CANCELLING -> CANCELLED
                                      \-> DECLINED
```

Phone ownership is verified before disclosure and again in the mutation
predicate. A token UUID supplied by the model is insufficient authorization.

### 6.5 WhatsApp connection

```text
NONE -> CONNECTING -> CONNECTED -> DISCONNECTING -> DISCONNECTED
                    \-> ERROR
```

Canonical `CONNECTED` requires `wa_status == connected` and a receiving
`wa_phone_number_id`. Disconnect is one database transaction that:

1. clears WABA, token, verified name, phone ID, and connection timestamp;
2. deletes branch-scoped working-memory conversations;
3. makes unsent outbox deliveries terminal;
4. commits the new state;
5. invalidates non-authoritative template/browser caches.

Chat APIs additionally join against connected branch state. Thus a stale row,
restored backup, old process, or browser cache cannot make patient text visible
while disconnected.

### 6.6 Soniox cloned voice

```text
LOCAL_CREATED -> UPLOADING -> PROCESSING -> READY -> ACTIVE
                            \-> FAILED
READY / ACTIVE -> DELETING -> DELETED
```

- Only an authenticated clinic owner can create, activate, or delete a clone.
- Creation requires an explicit recorded consent declaration and records the
  responsible user and timestamp.
- The reference clip is capped at 10 MB and 20 seconds. It is sent directly to
  Soniox's Japan endpoint and is not persisted in Vachanam storage.
- Soniox inventory is provider-project-wide, but Vachanam exposes and accepts
  only `BranchVoice` mappings for the authenticated branch. A provider UUID is
  not authorization.
- `ACTIVE` is legal only when Soniox reports the configured TTS model `ready`.
- A failed or processing voice can never reach the live agent.
- Deleting an active clone switches the branch to the safe catalog default
  before provider deletion. Soniox `404` is idempotent success.
- Upload uses a deterministic provider name so a response lost after provider
  acceptance can be reconciled rather than creating a duplicate clone.

## 7. Typed command and outcome contract

Handlers accept typed data, never prose:

```text
BookAppointment(branch_id, caller_phone, patient_name, doctor_id,
                service_date, session_id, slot_or_token, offer_version,
                command_id)

RescheduleAppointment(branch_id, caller_phone, booking_id,
                      replacement_offer, command_id)

CancelAppointment(branch_id, caller_phone, booking_id, command_id)
```

Handlers return one of a finite set:

```text
BOOKED | RESCHEDULED | CANCELLED | ALREADY_CANCELLED
NOT_FOUND | NOT_OWNED | DOCTOR_UNAVAILABLE | SLOT_UNAVAILABLE
OFFER_EXPIRED | VALIDATION_REQUIRED | CALENDAR_FAILED
TEMPORARY_FAILURE | POLICY_BLOCKED
```

Each result contains only verified structured fields. The channel renderer maps
`OutcomeCode + language + fields` to patient wording. A renderer cannot mutate
data; a handler cannot speak.

## 8. Deterministic workflow rules

### Start of inbound call

1. Resolve DID to exactly one active branch; zero or multiple matches fail
   closed and alert operations.
2. Create interaction ID and pin branch context.
3. Load the active roster/configuration snapshot.
4. Start the approved-language greeting; never include a different clinic's
   cached audio because every cache key includes branch and content digest.
5. Accept interruption only from qualified caller speech, not agent echo or a
   short backchannel.

### Doctor questions

1. Normalize the stated name/specialty.
2. Exact alias match within the active branch outranks conversational history.
3. Zero matches: truthfully say the clinic has no verified matching doctor.
4. One match: pin `doctor_id`.
5. Multiple matches: ask a bounded clarification; never pick one silently.
6. Availability is checked only after a date/time is known.

### Booking

1. Collect patient name; caller phone is automatic and immutable.
2. Resolve doctor ID from active branch data.
3. Resolve exact date and session; ambiguous relative dates are clarified.
4. Create a versioned offer from current availability.
5. Require explicit confirmation tied to that offer.
6. Execute idempotent booking command under capacity lock.
7. Render confirmation from committed result.
8. Queue WhatsApp confirmation using the same committed result.
9. Ask whether anything else is needed; end only after a negative answer,
   explicit goodbye, hangup, or silence policy.

### Reschedule and cancellation

1. Find only future appointments for caller phone + branch.
2. If several exist, enumerate safe identifying fields and require selection.
3. Verify ownership and current state immediately before mutation.
4. Require explicit confirmation of the exact operation.
5. Run one idempotent command.
6. Render only its result; never ask the model whether it succeeded.

### Unknown questions

1. Search verified clinic FAQ and structured settings.
2. If no verified answer exists, create one clinic-question row containing
   branch, caller name, caller number, channel, and question.
3. Acknowledge logging only after commit.
4. Doctor/receptionist answers or declines FAQ publication separately.
5. Deliver the answer on the originating channel with retry and idempotency.

## 9. Failure policy

| Failure | Deterministic patient outcome |
|---|---|
| STT uncertain/incomplete | Ask one narrow clarification using recognized context |
| Doctor not found | State no verified matching doctor; offer active specialties |
| DB unavailable | Say records cannot be checked now; do not state availability |
| Offer race lost | Say that exact option was just taken; re-query alternatives |
| Calendar failure | No booking confirmation; preserve/release capacity per command contract |
| LLM unavailable | Use deterministic intent fallback for supported operations or ask a bounded retry question |
| TTS failure | Retry/fallback approved voice; never expose text/control payload |
| WhatsApp disconnected | No inbound processing, no outbound enqueue, no chat disclosure |
| Notification failure | Booking remains committed; retry durable outbox |
| Voice clone processing failure | Keep the prior active voice; show the stable provider error category to the owner |
| Soniox voice API unavailable | Keep last known clone state; never expose project-wide inventory or activate an unverified clone |

Provider exception strings are never patient responses.

## 10. Database and concurrency rules

- Tenant scope is present in every primary lookup and mutation predicate.
- Unique constraints are the final duplicate barrier.
- Slot/token capacity uses a transaction-scoped advisory lock.
- Mutation tables store `command_id` with a uniqueness constraint or an
  equivalent idempotency record.
- Optimistic versions reject stale offers and stale dashboard updates.
- External side effects use an outbox/saga record with explicit states:
  `pending`, `in_progress`, `sent`, `cancelled`, `failed_permanent`.
- Retry workers claim rows with `FOR UPDATE SKIP LOCKED`.
- A reconnect creates a new connection generation; old-generation pending
  deliveries remain terminal.

## 11. Cache rules

- Caches accelerate reads and audio generation; they never authorize or prove
  availability.
- Every key includes `branch_id`, purpose/language, and source digest/version.
- Patient chat content is not shared across users, branches, or reconnects.
- Revocation removes browser query data synchronously and invalidates server
  caches after the database commit.
- On cache/database disagreement, discard cache and use database truth.

## 12. Observability without PII

Every interaction emits structured events keyed by interaction/turn/command,
branch ID, outcome code, and durations. Logs include phone last-four only and
never names, full phone numbers, question content, transcript text, credentials,
or medical details.

Required spans:

- ingress to greeting audio;
- last caller audio to STT final;
- intent/extraction;
- every authoritative query and command;
- lock wait and transaction duration;
- LLM first token;
- TTS first audio;
- carrier-ear response where recording consent permits measurement;
- notification enqueue and delivery outcome.

## 13. Verification gates

A release cannot be called correct solely because a prompt or happy-path demo
worked. It must pass:

1. Pure state-machine transition tests.
2. Outcome-renderer snapshot tests for every supported language.
3. Database-backed lifecycle tests.
4. Concurrent booking/reschedule/cancel races.
5. Cross-tenant IDOR and same-phone/different-branch tests.
6. Duplicate webhook and retry idempotency tests.
7. Interruption, incomplete-sentence, language-switch, and ragebait tests.
8. Provider timeout/failure injection tests.
9. “Success spoken iff commit succeeded” contract tests.
10. Production smoke check proving exact commit, migration head, worker
    registration, cache readiness, and one synthetic non-mutating query.

## 14. Implementation sequence

1. **WhatsApp lifecycle and chat revocation — implemented 2026-08-10.** One
   canonical connection predicate, one revocation transaction, API read gate,
   pending-delivery cancellation, and synchronous React Query erasure.
2. **Tenant-safe Soniox voice cloning â€” implemented 2026-08-10.** Consent
   provenance, bounded upload, branch-owned inventory, ready-only activation,
   preview, deletion fallback, and the clinic Voices page.
3. Introduce shared typed command/outcome contracts around existing booking
   tools without changing their proven locking logic.
4. Move every post-mutation voice/WhatsApp sentence to outcome renderers.
5. Add persistent command-id idempotency to booking, reschedule, and cancel.
6. Add offer versions and reject confirmations of stale offers.
7. Route dashboard and WhatsApp mutations through the same handlers.
8. Split the voice monolith into ingress, interpretation, policy, execution,
   rendering, and delivery adapters while preserving latency-critical warm
   connections.
9. Make the verification gates mandatory in CI and deployment automation.

This sequence preserves working behaviour while moving correctness out of the
prompt and into independently testable boundaries.
