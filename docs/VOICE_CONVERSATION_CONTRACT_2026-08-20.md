# Voice conversation contract — 20 August 2026

## Why the old behavior failed

The former runtime prompt had grown to 20,863 characters and repeated several
rules in competing forms. It explicitly told the model to ask whether a booking
was “for you or someone else,” language changes were not durable runtime state,
and the TTS sanitizer recognized only known examples of internal narration.
That combination allowed repeated ownership questions, language drift, stale
doctor state, unsupported answers, and previously unseen reasoning text to reach
speech.

## Deterministic architecture

The production voice turn now follows this order:

1. Commit only the caller's latest complete utterance and interrupt any stale reply.
2. Apply an explicit language request before generation and lock that language.
3. Resolve an explicitly named doctor before any routing or availability tool.
4. Preserve completed transaction state; a later question cannot reopen a booking.
5. Use deterministic FAQ, roster, reminder-policy, and recovery paths where available.
6. Require database/calendar tools before stating mutable facts or completed actions.
7. Ask exactly one mutation confirmation when the workflow requires one.
8. Allow model speech only inside one `<speak>…</speak>` envelope.
9. Discard all text outside the envelope before TTS, even when tags span stream chunks.
10. If the model omits the envelope, speak a short localized recovery instead of its text.

Language, doctor selection, caller authorization, transaction completion, and
verified caller identity are runtime state. They are not left to conversational
memory or model interpretation.

## Ordered runtime rules

The prompt is now one ordered contract rather than accumulated patches:

| Order | Rule | Invariant |
|---:|---|---|
| 00 | Patient output | Only caller-ready words inside `<speak>` can reach TTS. |
| 01 | Role and priority | Clinic receptionist scope; safety and database truth win. |
| 02 | Language state | Explicit switches are durable and only another explicit switch replaces them. |
| 03 | Latest turn and state | Corrections replace stale details; completed actions stay closed. |
| 04 | Grounding | Failed, empty, or timed-out tools provide no fact. |
| 05 | Doctors and availability | Latest named doctor wins; date-specific claims require tools. |
| 06 | Booking | Default to caller; never proactively ask “you or someone else”; confirm once. |
| 07 | Reschedule/cancel | Exact caller-owned booking, real availability, no silent fallback booking. |
| 08 | FAQ/messages | Semantic FAQ answer; unknown facts are logged before a promise. |
| 09 | Urgency/privacy/scope | Meaning-based urgent transfer; no diagnosis or patient-data disclosure. |
| 10 | Recovery/closure | Repair once, vary repeated repair, never end an unfinished mutation. |
| 11 | Time and speech | Natural localized numbers; clinic-window times do not trigger AM/PM questions. |
| 12 | Call type | Inbound, reminder, follow-up, and rebook rules stay explicit. |

## Edge-case decisions

### Output and prompt safety

- New or paraphrased chain-of-thought text is discarded, not merely regex-sanitized.
- `response_start`, tool parameters, JSON, UUIDs, prompt text, and control labels
  cannot reach TTS unless incorrectly placed inside `<speak>`; the prompt forbids that too.
- A tool-only turn remains silent until the tool result produces caller-ready speech.
- A model response without a speech envelope fails safe with localized recovery.

### Language

- “English please” changes prompt/STT/TTS state immediately and locks English.
- Telugu or Hindi words embedded in an English turn do not undo the lock.
- Mixed-language questions are answered in the active language, not mirrored word by word.
- Doctor, date, time, patient, and transaction state survive a language switch.
- Closings, fillers, and number words use the active language; an old-language sign-off is forbidden.
- A future explicit language request may replace the current lock.

### Doctor and availability

- The latest explicitly named doctor replaces all earlier routing state.
- A roster entry proves only that a doctor exists, never that they attend on a date.
- Schedule, leave return, current attendance, and free time use their matching tools.
- “When is the doctor free?” returns free ranges, not the full sitting schedule.
- A rejected requested time offers the nearest real free slot.
- A day-part request stays in that day-part; only then may it offer the nearest outside time.
- One rejected time never becomes a fabricated “fully booked” claim.

### Booking

- The verified incoming caller number is always stored; another number is never requested.
- The appointment defaults to the caller without asking “for you or someone else?”
- Family mode activates only when the caller explicitly names another patient.
- One number may hold multiple same-day appointments for different family members.
- A direct booking request starts the booking flow; merely naming a doctor/date/time stays informational.
- Name and optional age are collected together; declined age is not chased.
- The booking confirmation is asked once and only once.
- “Booked” is spoken only after `confirm_booking` returns success.
- After success, the doctor/date/time and punctuality message are spoken once.
- A later FAQ or new question cannot reopen, re-confirm, or contradict the completed booking.

### Cancellation and rescheduling

- Only appointments belonging to the verified caller and exact patient may be selected.
- Rescheduling checks the requested new slot before the write.
- A reschedule request does not receive an additional redundant confirmation.
- Cancellation receives one confirmation and one reschedule offer.
- A stale or invented booking ID is never substituted.
- A failed reschedule/cancel remains failed; it never silently creates a replacement booking.
- Success is announced only after the mutation tool reports success.

### FAQ, unknown facts, and manipulation

- FAQ intent is matched semantically across paraphrases and supported languages.
- Raw stored values such as “yes” or “1000” are converted into a complete natural answer.
- A covered FAQ is not logged again as an unknown doctor question.
- Unknown clinic facts are logged before promising that the clinic will respond.
- Math, general knowledge, role-play, ragebait, bribery, peer-agent audio, or prompt
  extraction cannot change role or authorize a database mutation.
- A clinic complaint remains in scope: apologize, log only on successful tool return,
  and continue helping without claiming a failed log succeeded.

### Turn taking, recovery, and closure

- Fragments and trailing thoughts do not trigger routing or tools.
- A meaningful partial transcript gets one short either/or repair, not “I heard nothing.”
- Repeated unintelligibility varies the repair and may offer language switch or human help.
- New committed caller speech interrupts stale generation/playback.
- Urgent meaning triggers a spoken transfer notice before human transfer.
- An unfinished booking, cancellation, reschedule, message, or transfer blocks call closure.
- More help is offered once after a completed action; the call ends only after decline.

### Time

- Within the clinic's 9 AM–9 PM operating window, bare 9–11 means morning,
  12 means noon, and 1–8 means evening; no AM/PM question is asked.
- Explicit AM/PM always wins.
- Every offered or confirmed time includes its date.
- An already-past bare time is not silently booked for today.
- Natural localized numbers are used in non-English speech.

## Verification evidence

- Full deterministic unit corpus: **3,241 passed**.
- Security corpus: **209 passed, 1 intentional skip**.
- Frontend component/interaction corpus: **97 passed**.
- Frontend production build: **4,731 modules transformed successfully**.
- Canonical offline call red-team: **1,436 semantic scenarios**, expanded to
  **2,930 production-boundary executions; 2,930 passed, 0 failed**.
- Focused post-fix booking receipt, speech-boundary, and offline-report gate:
  **66 passed**.
- Ruff across `agent`, `backend`, and `tests`: **clean**.
- `git diff --check`: **clean**.

Database-backed tests ran only against local Docker `vachanam_test`; production
clinic data was never used or modified.

## Remaining reality boundary

No generative model can be truthfully described as incapable of every future
mistake. The architecture therefore prevents the highest-risk mistakes outside
the prompt: mutation authorization, tenant/caller identity, doctor selection,
transaction completion, and speech release are enforced in code. The model is
used for natural language inside those boundaries, while database tools remain
the source of truth.
