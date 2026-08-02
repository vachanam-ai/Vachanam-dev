# Voice agent fix and latency verification

Date: 2026-08-02
Scope: latest production-call defects, latency, grounding, privacy, multilingual recovery, booking mutations, schedule truth, prompt caching, and UI preservation.

## Release result

- Full unit suite: **915 passed, 0 failed**.
- Booking/cancellation/reschedule/schedule lifecycle: **59 passed, 1 time-dependent skip, 0 failed**.
- Latest-call focused regressions: **137 passed**, plus **3 live-database proof tests**.
- Real Gemini multilingual adversarial evaluation: **114 passed, 0 failed**.
- Frontend production build: **passed**, 173 modules transformed.
- Frontend source changed by this work: **none**.

The complete 114-question evidence, including exact input, raw model answer, final text sent to TTS, execution path, latency, and verdict, is in [VOICE_ADVERSARIAL_EVAL_2026-08-02.md](./VOICE_ADVERSARIAL_EVAL_2026-08-02.md). The machine-readable artifact is [VOICE_ADVERSARIAL_EVAL_2026-08-02.json](./VOICE_ADVERSARIAL_EVAL_2026-08-02.json).

## Latest production call: defects confirmed

The production transcript and correlated timing records showed these concrete failures:

1. An unrelated opening utterance caused the agent to disclose an existing appointment and ask whether it was for the caller or someone else.
2. The call switched between English and Telugu out of sequence.
3. “Which doctors are available right now?” was answered with the full clinic roster, not the doctors whose current published shift was active.
4. Clear abuse such as “మీకు బుర్ర ఉందా?” repeatedly received “సరిగ్గా వినపడలేదు,” even though STT had produced meaningful words.
5. Incomplete phrases caused identical clarification loops.
6. An obvious jaw-pain complaint paid a separate Gemini routing call and took about 970 ms in that classifier alone.
7. A previous call had spoken “cancelled,” while the database still contained the appointment as confirmed. The later call then surfaced that record.
8. The first reply took 4.61 seconds in the correlated server trace. Later turns remained around two seconds and some exceeded four seconds.

## Fixes implemented

### Appointment privacy and first-turn contamination

Startup context no longer contains patient names, doctors, dates, times, token IDs, reminder state, or appointment details. A database match on the inbound number does not greet by a stored patient name and does not reveal that an appointment exists. Appointment records are fetched only after the caller explicitly asks, through `find_my_bookings`, which is scoped to the verified inbound number.

This removes the exact mechanism that made the agent answer an unrelated first utterance with “You have an appointment with Doctor Srinivas…”

### Current doctor availability

“Who is available right now?” is now a deterministic database operation, not a prompt interpretation. A single tenant-scoped query applies this precedence:

1. doctor leave for the exact date;
2. exact-date published sessions;
3. recurring multi-session schedule;
4. unpublished date-specific schedule means unknown and is never inferred as available.

The response says a doctor is **scheduled/on shift**. It never claims that an appointment slot is free; an actual slot still requires `check_availability`.

### Better recovery instead of “I can’t hear properly”

Meaningful final transcripts may no longer be described as an audio failure. Recovery is deterministic and changes on each unresolved fragment:

1. “చెప్పండి అండి, తొందరేమీ లేదు. ఏం అడగాలనుకున్నారు?”
2. “డాక్టర్ గురించా, టైమ్ గురించా, లేక అపాయింట్‌మెంట్ గురించా అండి?”
3. “మీరు చిన్న వాక్యంలో చెప్పగలరా అండి, లేక క్లినిక్ సిబ్బందితో మాట్లాడాలా?”

Clear ragebait receives a calm, same-language response and never changes the agent into a patient: “మీకు కోపంగా ఉందని అర్థమవుతోంది అండి. ఇప్పుడు ఏ సహాయం కావాలో చెప్పండి, నేను చేస్తాను.”

The true one-way-audio message remains only behind the separate hard signal of three consecutive lone “hello” turns.

### Language and role stability

Native-script language correction occurs before Gemini and carries the current utterance into the correct language agent. Control-label attacks, legal threats, roster/current-shift questions, fragments, and recognized abuse are answered before the model. The TTS boundary also strips response labels, tool narration, hidden instructions, and reasoning-like output.

### Faster complaint routing

Conservative multilingual specialty aliases were added for dental, skin, child/pediatric, orthopaedic, and ENT complaints. A local result is accepted only when exactly one active clinic doctor matches. Ambiguous or unsupported complaints still use the classifier.

The latest call’s Telugu jaw-pain phrase now routes locally to the dental doctor and the regression test fails if Gemini is called.

### Booking, reschedule, and cancellation truth

Mutation speech remains deterministic and is emitted only after the write returns success. Cancellation commits database truth first. Google Calendar deletion is now inserted into the durable retry queue instead of blocking the caller for up to five seconds after the database already committed.

Reschedule still creates and confirms the replacement before cancelling the original. If old cancellation fails, the replacement is compensated so the agent cannot claim a move while leaving two live appointments. Stale token IDs from multiple same-call reschedules are mapped to the current replacement rather than guessed.

After a successful booking, the deterministic line includes “Please come on time” and “Is there anything else I can help you with?” If the caller speaks, the conversation continues; otherwise the short closing timer ends the call instead of waiting through a 30-second line-check cycle.

### Prompt caching and startup configuration

The shared cached prompt contains stable clinic facts and tools. Clock/date, caller state, and private call data remain in runtime chat context outside cached content. This allows one clinic-wide prompt cache to serve different callers safely.

Sarvam is no longer a required startup setting. Production speech is Soniox STT and Soniox TTS on the Japan endpoints. Sarvam remains only as an explicitly selected STT fallback and as a best-effort transliteration/name-pronunciation helper. The Render manifest no longer requests Sarvam or smallest.ai secrets.

### Telemetry correctness

Negative or out-of-order durations are discarded rather than reported as real latency. Stale playout edges from the prior agent response no longer contaminate the next turn. Telemetry session IDs are pseudonymized and do not contain the caller number.

## Latency evidence

### Last production call before these fixes

From 22 valid correlated turns:

| Stage | Observed |
|---|---:|
| Caller last word → first audio, p50 | 1,745 ms |
| Total server turn, p50 | 1,669 ms |
| Total server turn, p95 | 3,992 ms |
| First turn total | 4,614 ms |
| Soniox finalization, p50 | 333 ms |
| Soniox finalization, p95 | 2,622 ms |
| Gemini first token, p50 | 574 ms |
| Gemini first token, p95 | 658 ms |
| Soniox first audio, p50 | 510 ms |
| Soniox first audio, p95 | 997 ms |

The first turn’s 4.61 seconds was composed mainly of 2.62 seconds waiting for STT finalization, 0.77 seconds for Gemini’s first token, and about 1.00 second for Soniox’s first audio. The slowest later tail was also STT finalization, at about 2.81 seconds.

### Code-path improvements in this release

- Current-shift, roster, fragment, control-label, legal-threat, and ragebait turns remove Gemini completely.
- High-confidence specialty routing removes the extra classifier call; the latest jaw-pain path removes about 970 ms of measured work.
- Stable prompt caching is shared across callers and is prewarmed for clinic/language variants.
- Cancellation removes inline Google Calendar network latency from the caller path.
- Successful mutation confirmation skips the redundant post-tool LLM pass.
- VAD still reports a possible boundary after 60 ms, Soniox receives a cancellable manual finalize after 200 ms of continuing silence, and preemptive generation/TTS remain enabled.

For deterministic non-tool turns, the expected warm floor on the current remote stack is approximately STT finalization plus TTS first audio: roughly **0.8–1.0 seconds at the measured medians**. A normal cached Gemini reply is expected around **1.3–1.6 seconds**. These are engineering projections, not post-deployment PSTN measurements.

The present Soniox-Japan + Vertex-Mumbai + Soniox-Japan topology cannot honestly guarantee 500 ms end to end because the measured median external stages alone are approximately 333 + 574 + 510 ms before overlap. A sub-500-ms guarantee requires a materially different co-located or speech-to-speech provider path. The deployed timestamp trace will show the exact post-fix result on the next real call.

## Adversarial proof

The evaluator asked 114 questions across Telugu, Hindi, Tamil, Kannada, Marathi, and English. Coverage included:

- abuse and ragebait;
- incomplete and trailing-off speech;
- mid-call language switching;
- secrets, system prompt, database password, and API-key requests;
- requests for other patients’ appointments;
- prompt injection and private-context extraction;
- role reversal by another AI agent;
- `response_start`/control-label requests;
- thinking-out-loud and hidden-instruction requests;
- general/off-topic questions.

Final result: **114/114 passed**. The final execution split was:

| Execution path | Cases |
|---|---:|
| Deterministic incomplete recovery | 24 |
| Deterministic hostile recovery | 8 |
| Deterministic current-shift database answer | 4 |
| Deterministic clinic roster | 2 |
| Deterministic legal-threat response | 6 |
| Deterministic control-label refusal | 6 |
| Gemini followed by the production TTS guard | 64 |

The remaining 64 Gemini calls measured 1,512 ms average, 1,409 ms p50, 2,528 ms p95, and 3,002 ms maximum in the final model-level evaluator run. These are not telephone end-to-end numbers.

## Transactional proof

The 59 passing lifecycle tests covered:

- token and scheduled doctors;
- multiple daily sessions and gaps;
- exact-date schedules and unpublished dates;
- leave precedence;
- exact requested time and nearest-slot behavior;
- booking confirmation and caller authorization;
- family members sharing one verified caller number;
- cross-caller privacy rejection;
- cancellation and already-cancelled behavior;
- repeated rescheduling with stale IDs;
- failed replacement rollback and compensation;
- interrupted mutation recovery and idempotency;
- durable Calendar cleanup after cancellation.

There were no failed booking, cancellation, reschedule, or schedule-truth cases. One test was skipped because its scenario depends on the current wall-clock schedule.

## Verification commands

```text
python -m py_compile agent/livekit_minimal/agent.py backend/services/doctor_schedule.py agent/tools/booking_tools.py
Result: passed

python -m pytest tests/unit -q
Result: 915 passed

python -m pytest <booking/reschedule/cancel/torture/schedule files> -q
Result: 59 passed, 1 skipped

python scripts/run_voice_adversarial_eval.py --language all ...
Result: 114 passed, 0 failed

npm run build
Result: passed, 173 modules transformed

git diff --check
Result: passed
```

## Proof boundary

These results prove the checked decision paths, sanitization, database transactions, and multilingual model responses under the documented tests. No test can prove that a telephone carrier or remote speech/model provider will never have a latency tail or outage. Production proof therefore has two stages: deploy this exact commit and verify worker registration/cache warmup, then correlate the next real call’s transcript with STT-final, Gemini-first-token, TTS-first-audio, and playout timestamps.
