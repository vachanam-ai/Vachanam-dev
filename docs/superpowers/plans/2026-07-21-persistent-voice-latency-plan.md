# Persistent Voice Latency Reduction Plan

**Date:** 2026-07-21  
**Status:** Ready for implementation  
**Scope:** Caller stops speaking → caller hears the first word of Vachanam's reply  
**Primary language gate:** Telugu over real 8 kHz telephone audio

## Goal

Reduce the remaining perceived turn gap without weakening Telugu recognition,
booking correctness, privacy filters, interruption behaviour, or provider
fallbacks.

This is not another broad tuning pass. Every experiment changes one variable,
uses the same call corpus, records p50/p95 rather than an average, and has an
environment-only rollback wherever possible.

## Current production baseline

The following latency work is already active and must be treated as the
baseline, not proposed again:

| Stage | Current implementation |
|---|---|
| STT | Soniox v5, Japan endpoint, endpoint latency level 1, 2000 ms tail cap, default sensitivity |
| Turn finalization | Session-scoped manual finalize after 200 ms of continuing silence; cancelled if speech resumes |
| LiveKit endpointing | `min_endpointing_delay=0.05`, `max_endpointing_delay=0.3`, preemptive generation enabled |
| LLM | Gemini 2.5 Flash on Vertex Mumbai, thinking disabled; global Gemini fallbacks |
| Prompt | Compact grounded prompt, real-prompt prewarm and explicit Vertex prompt cache for eligible calls |
| TTS | Streaming Smallest primary, REST fallback, warmed during call setup |
| Slow tools | Pre-cached short filler while availability/booking/reschedule/cancel work runs |
| Existing metrics | Separate `lat_eou`, `lat_llm`, `lat_tts`, and `lat_stt` log lines |

The old measured sequential lower bound was roughly 1.6 seconds before
transport overhead. The latest changes should improve that, but the caller
still perceives about three seconds. The existing metric lines are not joined
by turn, and they do not measure several intervals between the stages. We
therefore cannot safely choose the next knob from the current logs.

## Non-negotiable constraints

1. Never reduce latency by accepting worse names, doctors, dates, times, phone
   numbers, symptoms, or code-mixed Telugu.
2. Never start a booking mutation from an interim transcript.
3. Never weaken the internal-tool-speech firewall or expose identifiers to TTS.
4. Never reintroduce the automatic thinking acknowledgement. It previously
   fired between the agent's own sentences and made calls worse.
5. Never change two STT endpoint controls in the same experiment.
6. A booking confirmation still follows a successful atomic write and calendar
   write; latency work cannot move speech ahead of truth.
7. All production changes remain reversible through one environment variable
   or one small revert.

## Success criteria

Measure from the physical end of caller speech to the first audible agent PCM
frame, not merely to an LLM token.

| Cohort | p50 target | p95 target |
|---|---:|---:|
| Warm, non-tool turn | <= 1.3 s | <= 2.0 s |
| First caller turn | <= 1.6 s | <= 2.5 s |
| Slow-tool turn: first cached acknowledgement | <= 1.3 s | <= 2.0 s |
| Tool completion → final spoken result | <= 0.8 s | <= 1.3 s |

Quality gates:

- no material entity-accuracy regression on patient name, doctor, date, time,
  phone number, complaint, or treatment term;
- premature turn commits below 1% of representative turns;
- no increase in fragmented long utterances;
- a lone hello/backchannel does not interrupt the agent;
- a genuine multi-word interruption still stops speech promptly;
- all booking, branch-isolation, TTS-safety and mutation-interruption tests pass.

## Phase 1 — Make one turn fully measurable

**Purpose:** Identify the dominant remaining delay before changing behaviour.

### Task 1.1: correlated per-turn trace

Add a small `TurnLatencyTrace` owned by one call session. Each completed caller
turn gets a monotonically increasing `turn_seq`. Record monotonic timestamps for:

1. VAD speech end;
2. manual-finalize scheduled and sent;
3. final STT transcript received;
4. LiveKit user turn committed;
5. preemptive LLM generation started, reused or cancelled;
6. first LLM token;
7. first patient-safe text yielded by the internal-speech guard;
8. TTS request start;
9. first TTS audio frame;
10. agent playout/speaking start;
11. tool start, filler start, tool end and post-tool first audio when applicable.

Emit one structured summary after first playout:

```text
voice_turn_latency session=<masked> turn=4 kind=tool language=te
total_ms=... stt_finalize_ms=... livekit_commit_ms=... llm_ttft_ms=...
safety_buffer_ms=... tts_ttfb_ms=... playout_ms=... unaccounted_ms=...
cache_hit=true provider=vertex tool=check_availability
```

Do not log transcript text, patient data, phone numbers, doctor names, or tool
arguments. A session identifier may be hashed/truncated.

### Task 1.2: latency report script

Add `scripts/analyze_voice_latency.py` to consume exported structured log lines
and report p50/p95/p99 by:

- first turn versus later turn;
- simple conversation versus tool call;
- prompt-cache hit versus miss;
- primary LLM versus fallback;
- STT provider;
- language;
- warm versus cold TTS stream.

The report must also display `unaccounted_ms`. If more than 100 ms remains
unattributed at p50, instrumentation is incomplete and tuning pauses.

### Task 1 acceptance

- Unit tests prove turn IDs cannot cross sessions or language handoffs.
- Out-of-order LiveKit metrics cannot attach to the wrong turn.
- Missing metrics produce `null`, not a false zero.
- A privacy test rejects transcript/phone/name fields in the summary.
- Five local scripted turns produce one coherent line per turn.

## Phase 2 — Establish the post-#443 baseline

Use the exact current production configuration. Do not change provider or
endpoint controls during collection.

Collect at least:

- 30 calls and 200 complete turns;
- short replies, hesitant multi-clause requests, code-mixed Telugu-English,
  doctor/date/time/name/number entities;
- first turns and warm later turns;
- ordinary questions, routing, availability, booking and rescheduling;
- at least 50 turns over real PSTN 8 kHz audio.

Use consented, de-identified replay audio for repeatable comparisons, followed
by a small live-call sample. Preserve the exact same corpus for every arm.

Record subjective feedback separately from timing: `fast`, `acceptable`, or
`slow`. Do not infer timing from conversational feeling alone.

### Phase 2 decision gate

Choose the next phase from the measured dominant stage:

| Dominant measured delay | Next action |
|---|---|
| `unaccounted_ms` > 100 ms p50 | Find framework/transport buffering before provider tuning |
| STT/finalization misses budget | Phase 4 STT experiment |
| LLM TTFT misses budget | Phase 3 LLM/cache work |
| LLM token → safe-text yield is slow | Phase 3 speech-firewall streaming work |
| TTS/playout misses budget | Phase 5 TTS work |
| Only tool turns are slow | Phase 6 tool-path work |

Only the dominant branch is implemented first. Re-run the same corpus before
starting another branch.

## Phase 3 — Remove avoidable LLM and buffering delay

Do this only when the baseline points to the LLM or the text-to-speech handoff.

### Task 3.1: prove prompt cache effectiveness

Log, per turn, the selected LLM, cache eligibility, cache hit, estimated prompt
size and TTFT. Compare four cohorts: anonymous cache hit/miss and known-caller
cache hit/miss.

The current cache excludes calls containing caller-specific or outbound context.
If misses explain the latency, split the prompt into:

- a stable cached instruction/tool prefix; and
- a small private per-call context message containing date, caller booking and
  outbound purpose.

The dynamic context must remain delimited as private data, must not be treated
as caller instruction, and must pass the existing prompt-injection and private-
speech tests. If the LiveKit Gemini adapter cannot combine cached tools with a
safe dynamic context, keep the current path; do not create a custom cache layer.

Promotion gate: at least 150 ms p50 TTFT improvement with identical tool choice
and response correctness.

### Task 3.2: measure the speech firewall buffer

The internal-speech stream currently carries 24 characters before yielding.
Measure `first_llm_token → first_guard_yield`. If it contributes more than 100 ms
at p50, replace the fixed carry with the smallest prefix-aware streaming matcher
that can still detect every split internal marker.

The security test must split every forbidden marker at every character boundary
and prove none reaches TTS. No latency win is accepted if that test weakens.

### Task 3.3: model A/B only if TTFT remains dominant

Benchmark the two model paths already deployed—Vertex Mumbai Gemini 2.5 Flash
and the existing Gemini Flash Lite fallback—on the same full prompt and tool
schema. Compare TTFT, tool-call correctness, Telugu response quality and p95
spikes. Promote only if the challenger wins latency and does not lose correctness.

Do not add a new LLM vendor in this phase.

## Phase 4 — Controlled STT endpoint experiments

Do this only if speech-end/STT remains over budget after correlated tracing.

The current arm is:

```text
S0 = Soniox level 1 + sensitivity default + cap 2000 ms + manual finalize 200 ms
```

Run one-variable arms in this order:

| Arm | Single change from S0 | Purpose |
|---|---|---|
| S1 | endpoint latency level 2 | Lower semantic endpoint latency |
| S2 | manual finalize disabled | Prove whether the 200 ms path is helping rather than racing vendor finalization |
| S3 | max endpoint delay 1500 ms | Reduce p95 only if manual finalize occasionally does not fire |
| S4 | sensitivity +0.1 | Last Soniox tuning step, only if S1–S3 are accurate but insufficient |
| S5 | force existing Sarvam provider | Low-effort provider A/B using the integration already present |

Never combine S1, S3 and S4 until each has independently passed. Do not restore
the failed immediate-finalize, 800 ms cap, sensitivity 0.3 configuration.

Each arm needs at least 200 replayed turns and a small live canary. Reject an arm
for any entity error increase, clipping, false commits, fragmented speech, or
premature response to a thinking pause—even when its median is faster.

## Phase 5 — TTS and first-audio path

Do this only if TTS request-to-playout exceeds 300 ms p50 or 600 ms p95.

1. Distinguish Smallest streaming-primary calls from REST-fallback calls in the
   latency summary. A fallback must not be mistaken for normal TTS performance.
2. Verify the warm streaming probe completes before the first user turn.
3. Measure WebSocket connection, first request byte, first PCM frame and LiveKit
   playout separately.
4. Reuse a TTS connection only if the provider and LiveKit plugin support it
   safely; otherwise retain the current per-stream implementation.
5. Keep replies front-loaded and short so a speakable clause reaches streaming
   TTS early. Do not wait for the complete LLM response.

No change may bypass digit conversion, script validation, AGC, or internal-
speech filtering.

## Phase 6 — Slow-tool and deterministic-response path

Availability and booking turns include database, Redis and Google Calendar work.
Treat them separately from ordinary conversation.

### Task 6.1: tool substage tracing

For each slow tool, log masked durations for DB, Redis, Calendar, WhatsApp and
total execution. Confirm the cached acknowledgement begins promptly and only
once.

### Task 6.2: safe parallelism

Parallelize only independent read operations. Calendar and capacity checks used
for final confirmation remain authoritative. A short-lived cache may help offer
availability, but `confirm_booking` must always re-check the live slot and retain
its atomic Redis/Postgres guards.

### Task 6.3: deterministic success lines

If post-tool LLM generation is the dominant delay, return a patient-facing,
native-script `spoken_response` from successful booking, reschedule and cancel
operations and play it directly. This can remove a second LLM turn from the most
important clinic actions.

Requirements:

- templates for every supported language;
- appointment doctors announce date/time only;
- token doctors announce token only;
- include the requested “please come on time” closing;
- use the existing date, time, digit and TTS sanitizers;
- never speak before the transaction and required calendar write succeed;
- suppress the normal post-tool LLM reply so the confirmation is spoken once.

Start with booking/reschedule/cancel only. Do not build a general template engine.

## Phase 7 — Provider escalation only if the target still fails

If the dominant stage remains STT after the Soniox and existing Sarvam arms,
benchmark one challenger from `docs/SONIOX_LATENCY_RESEARCH.md` against the same
corpus. Choose the best paper candidate first; do not integrate several vendors
in parallel.

The benchmark must measure physical speech end to safe final turn, not vendor
time-to-first-partial-transcript claims. A provider is eligible only if it meets
the entity and endpoint gates on Telugu PSTN audio.

## Rollout procedure

For every behavioural experiment:

1. land tests and structured startup logging;
2. run focused latency, STT, prompt, interruption, TTS-safety and booking tests;
3. run Ruff and the full repository suite;
4. deploy one variable during a controlled call window;
5. verify the worker registered and logs the intended effective configuration;
6. run the fixed live-call script;
7. compare the report with S0;
8. keep or roll back before starting the next arm;
9. soak the winner for 24 hours and inspect p95 plus failure tags.

Environment rollbacks:

- STT provider: `STT_PROVIDER=auto|soniox|sarvam`;
- Soniox controls: `SONIOX_ENDPOINT_LATENCY_LEVEL`,
  `SONIOX_MAX_ENDPOINT_DELAY_MS`, `SONIOX_ENDPOINT_SENSITIVITY`,
  `SONIOX_MANUAL_FINALIZE_DELAY_MS`;
- every newly introduced behavioural path must have an equivalent off switch
  until its 24-hour soak passes.

## Recommended implementation order

1. Correlated per-turn trace and report script.
2. Current-production baseline on the fixed corpus.
3. Fix only the measured dominant hidden buffer or LLM/cache issue.
4. Run Soniox level 2 as the first endpoint experiment only if STT remains slow.
5. Add deterministic booking/reschedule/cancel success speech if post-tool LLM
   latency is material.
6. Force the existing Sarvam A/B only if Soniox cannot meet the gate.
7. Consider one new STT provider only after all existing low-cost levers fail.

## Definition of done

The work is complete when:

- the p50 and p95 targets hold over at least 500 production turns and 48 hours;
- the measurement accounts for all but 100 ms of the total p50 gap;
- Telugu entity accuracy and interruption behaviour pass their gates;
- no private execution text reaches TTS;
- booking/rescheduling/cancellation regressions remain green;
- startup logs show the effective provider/model/configuration;
- the winning configuration and measured before/after distributions are added
  to `FIXLOG.md` and `STATUS.md`.

## Explicitly deferred

- multi-region voice deployment;
- replacing LiveKit or rewriting the voice stack;
- adding multiple new STT vendors at once;
- generic speculative speech or automatic thinking fillers;
- weakening booking/calendar consistency to make a tool appear faster.

These do not address the next measured bottleneck and would add risk before the
current pipeline is fully attributed.
