# Booking Reliability Audit — 16 August 2026

## Executive result

The WhatsApp cancellation/rescheduling loop shown in the incident screenshots was reproduced against the production records, traced to a concrete state-loss defect, and fixed in the shared WhatsApp booking path.

The failure was not caused by appointment availability or by Meta's username notice. The verified appointment existed in the database, but the assistant's hidden tool result (including the appointment UUID) was not persisted between WhatsApp messages. When the patient answered “Yes please” in a later message, the model no longer had the verified UUID and supplied an invalid one. The ownership guard correctly refused to mutate a booking with that invalid ID, producing the repeated failure seen in the screenshots.

The fix makes the database—not model memory—the source of appointment identity across turns.

## Production incident evidence

- The matching WhatsApp conversation was found for the correct clinic and caller scope.
- Its stored session contained the visible conversation but an empty booking draft.
- The database contained a confirmed Dr. Lakshmi appointment for the requested patient/time.
- The displayed failures corresponded to mutation calls made without a usable verified appointment UUID.
- Production was inspected read-only; the patient's appointment was not changed during diagnosis.

Patient names, full phone numbers, and record identifiers are intentionally omitted from this report.

## Architecture correction

1. `my_appointments` now stores the exact branch-scoped, caller-owned appointment identifiers in the encrypted/persisted WhatsApp session draft.
2. When booking discovers an existing appointment and asks whether it should be moved, the exact existing UUID and proposed target time are persisted as a pending reschedule.
3. A later reply such as “yes”, “please do it”, or its regional-language equivalent receives that verified state as hidden internal context. IDs are explicitly forbidden from patient-visible output.
4. Before reusing stored state, appointments are fetched again from the database. IDs removed or changed by another channel are discarded.
5. Cancel/reschedule tools still enforce clinic, branch, and caller ownership. A guessed or foreign UUID cannot mutate data.
6. If an ID is stale, the tool returns a fresh list of only that caller's appointments so the assistant can recover in the same turn instead of looping.
7. Booking, cancellation, and rescheduling state is cleared only after the database mutation reports success.
8. An empty appointment result clears stale draft state, avoiding permanent extra database reads.

## Deterministic scenario matrix

The generated matrix exercises 6,720 combinations:

- 8 language/region profiles: English, Telugu, Hindi, Tamil, Kannada, Malayalam, Marathi, and Bengali
- 5 doctors
- 7 dates
- 6 time shapes, including boundary/noon cases
- 4 patient relationships: self, child, parent, and spouse

Every scenario verifies that the exact UUID, doctor, date, time, and family-member relationship survive a WhatsApp message boundary while the UUID remains hidden from patient-facing text.

Additional focused cases cover:

- existing appointment → propose move → separate “Yes please” → successful reschedule
- stale/invalid mutation ID → fresh owned appointment recovery
- no owned appointments → no stale pending action
- successful book/reschedule/cancel → draft state cleared
- two appointments owned by the same caller without cross-patient disclosure
- clinic/branch/caller ownership enforcement
- repeated confirmations and retries remain idempotent

## Test proof

### Current final patch

- Focused WhatsApp/session/booking tests: **82 passed**
- Frontend: **66 passed** across 17 files
- Frontend ESLint: **passed**
- Frontend production build: **passed** (4,731 modules transformed)
- Python compile checks for changed runtime modules: **passed**

### Broad backend certification run

- Unit: **1,775 passed**
- Security and edge cases: **209 passed, 1 skipped**
- Integration: **707 passed, 8 skipped**
- Total: **2,691 passed, 9 skipped** across **2,700 collected tests**

The final empty-state performance correction was then rerun through the 82-test focused suite.

### Live-model isolated journeys

The optional E2E journey used the real Gemini model with a temporary isolated database. Meta delivery and Google Calendar were stubbed to prevent messages or appointments reaching real people.

One complete English journey passed:

1. clinic greeting and doctor roster
2. availability lookup
3. self booking
4. second family-member booking on the same caller number
5. family-member reschedule with ownership preserved
6. existing-booking move offer instead of a false “slot unavailable” answer
7. self-booking cancellation
8. final database-state verification

The exact reported regression also passed independently with a real model:

1. seed a confirmed 10:00 appointment
2. request a move to 10:30
3. assistant identifies the existing booking
4. patient answers in a separate message: “Yes please”
5. the persisted exact UUID is used
6. the old appointment becomes cancelled and one new 10:30 appointment is confirmed

The isolated live run also exposed non-transactional observations: Windows console encoding could not print some Indic text; a deliberately underspecified request asked for a doctor; and one English request reconfirmed an age rather than immediately booking. None caused a false database mutation. The console issue is a test-runner display limitation, not a production WhatsApp encoding failure. The cautious clarifications are preferable to silently choosing a doctor or patient detail.

## What this proves—and what it does not

This proves the application logic, ownership boundaries, state persistence, database transactions, frontend build, and model-assisted multi-message flow under the tested configurations.

It does not honestly prove that Meta, a telecom carrier, Google Calendar, regional networks, or every future model response can never fail. Those are external systems. Production confidence requires canary monitoring and delivery receipts in addition to tests. The code is designed to fail closed: it must not tell the patient a booking changed unless the mutation succeeded.

Before broad rollout, run one canary per real channel and clinic:

- WhatsApp book, reschedule, cancel, and delivery receipt
- voice book, reschedule, cancel, interruption, and call completion
- Google Calendar create/update/delete reconciliation
- reminder and follow-up dispatch at the configured timezone
- two clinics concurrently to verify DID and branch isolation

## Meta username / BSUID notice

The popup is an account-readiness notice for Meta's future username rollout. It is unrelated to this cancellation/rescheduling defect. Reserving the preferred username is reasonable, but Vachanam should continue using the existing phone-number identifiers until Meta exposes the rollout for this account and the webhook payloads can be verified. The safe migration design is dual identity: retain the current phone identity and add the business-scoped identifier as an alias, never replace the existing patient key in place.

No BSUID production migration was made in this change.
