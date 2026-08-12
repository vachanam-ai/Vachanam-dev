# Production E2E audit — 2026-08-11

## Release verdict

**Hotfix deployed as `a9fa516`; the deterministic reminder crash is repaired.**
Booking, rescheduling, cancellation, Google Calendar cleanup, database truth,
and slot release passed the controlled real production lifecycle. A safe
post-deploy dispatch using the cancelled E2E token proved that the Fly worker
re-read database state, logged `reminder_dial_blocked state=not_confirmed`, and
exited normally without invoking the SIP dial API. A genuinely due, answered
reminder is still required to certify carrier delivery and spoken audio.

This report deliberately does not claim that the system can never fail or can
serve an unlimited number of clinics. Those claims are not supportable with the
current single-machine/single-worker production topology.

## Controlled real production lifecycle

Test data was pseudonymous (`Vachanam E2E QA`) and only the caller's last four
digits are reported here (`7554`). The normal production service functions were
used against the production database and the clinic's configured Google
Calendar.

| Stage | Production result | Evidence |
| --- | --- | --- |
| Grounded availability | Passed | The shared schedule resolver read Sri Venkateshwara / Dr Lakshmi's active exact-date schedule and returned the real open grid for 2026-08-12. |
| Book 10:30 | Passed | Token suffix `fd34` was committed as `confirmed` only after a Google Calendar event ID was returned and persisted. |
| Reschedule 10:30 → 10:45 | Passed | Old token became `cancelled_by_patient`; replacement token suffix `1280` became `confirmed` with its own persisted calendar event. |
| Remove old calendar event | Passed | Durable delete task reached `done`, zero retries and no error. |
| Cancel 10:45 | Passed | Database status and a durable calendar-delete task committed together. WhatsApp correctly reported `branch_disconnected` internally and did not claim a message was sent. |
| Remove replacement calendar event | Passed | Production calendar worker moved the delete task to `done`, zero retries and no error within one scheduler cycle. |
| Release capacity | Passed | The same production availability resolver showed both 10:30 and 10:45 free again; 15 total free slots remained. |
| Test-data cleanup | Passed | No controlled test appointment remains confirmed. The cancelled audit rows remain as the intentional lifecycle record. |

## Real reminder result

The backend accepted the real LiveKit reminder dispatch, but the deployed Fly
voice job crashed before it could speak:

```text
2026-08-11T17:47:10Z
TypeError: Logger._log() got an unexpected keyword argument 'state'
/app/agent/livekit_minimal/agent.py, deployed line 6591
```

An older production reminder at 11:40:50Z showed the same exception. This is a
deterministic code defect, not a carrier timing guess.

Local repair:

- Replaced both invalid stdlib logging calls with positional `%s` arguments.
- Added an AST regression test that rejects unsupported keyword arguments on
  stdlib logger calls.
- Reminder-focused regression: **29 passed**.
- Combined reminder + WhatsApp booking-agent regression: **78 passed**.

The fix was pushed and deployed as production build `a9fa516` / Fly release
v296. The safe post-deploy guard probe exercised the previously crashing line
without an exception.

## Booking transaction hardening added locally

- WhatsApp cancellation now locks the caller-owned token and commits the token
  cancellation plus a durable Google Calendar delete task in one database
  transaction. A transient Google outage no longer silently strands an event.
- WhatsApp reschedule remains replacement-first. It now verifies cancellation
  of the original booking; a race rolls back the replacement and returns an
  explicit non-success outcome instead of claiming the move succeeded.
- Added integration coverage for transaction coupling and the reschedule race.

These changes are deployed in production build `a9fa516`.

## Automated evidence

- Unit suite: **1,661 passed**.
- Production-critical security and edge suite: **186 passed, 1 skipped**,
  including tenant isolation, DID hijack protection, rate limits, 100 concurrent
  token allocations, and same-slot concurrency.
- Lifecycle integrations: **160 passed, 1 skipped**.
- WhatsApp integrations: **195 passed**.
- Billing: **73 passed**.
- Remaining integration partitions: **258 passed, 7 skipped**.
- Frontend: **41/41 tests passed**, ESLint passed, production Vite build passed.
- Current collection sees **2,513 tests**. Four collection errors are from old
  Windows output directories with denied ACLs, not application/test modules.
- `git diff --check`: no whitespace errors.

## Live production health at audit end

- API: `status=ok`, `env=production`, build `3582254`, RSS 256 MB.
- Scheduler: healthy.
- Reminder wake age: 49.1 seconds.
- Calendar writer wake age: 50.2 seconds.
- WhatsApp delivery worker wake age: 50.2 seconds.
- Fly voice: one started Mumbai machine, version 295; worker registered to
  LiveKit India West.

## What could not be truthfully certified tonight

### One-hour reminder

The production reminder policy intentionally skips appointments created within
60 minutes of their appointment, and no doctor had a genuine published clinic
session one hour from the late-night test. Creating fake after-hours doctor
availability would violate the database-grounding requirement. The real manual
dispatch instead exposed the voice crash above.

### WhatsApp confirmation and follow-up delivery

Both current clinic branches are WhatsApp-disconnected, so no real WhatsApp
confirmation/follow-up can be delivered. The correct tested behavior is to skip
delivery without claiming success. Sri Skincare also has no branch-specific
outbound trunk; borrowing Sri Venkateshwara's trunk is prohibited because it
would recreate the prior cross-clinic caller-ID leak.

### Unlimited clinic scale

Production currently has:

- one Fly voice machine (four pre-warmed job processes), and
- one Render free web worker that can cold-start and whose migrations are not
  automatically applied.

This is suitable for controlled early traffic, not an unlimited-clinic
guarantee. Before onboarding meaningful concurrent traffic, production needs a
paid always-on backend, at least two active voice machines with measured
concurrency limits, automatic migration gating, queue-depth/SLO alerts, and a
staged load test at the expected peak concurrent-call count.

## Required next release gate

1. **Done:** clean hotfix created from production build `3582254`; the current
   sandbox-history branch was not deployed wholesale.
2. **Done:** only the reminder logger repair, WhatsApp transaction hardening,
   and their regression tests were released.
3. **Done:** backend build `a9fa516` and Fly v296 deployed with healthy workers.
4. Connect a clinic-specific outbound trunk and WhatsApp configuration where
   external delivery is to be certified.
5. Create a genuine appointment more than 60 minutes ahead, observe the normal
   scheduler (not a manual bypass), capture ring/answer/first-audio timestamps,
   and verify the post-call reminder state.
6. Create a consented follow-up task inside 09:00–20:00 clinic-local courtesy
   hours and verify call delivery, spoken content, writeback, and idempotency.

