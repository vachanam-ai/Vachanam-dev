# Sub-500ms Voice Latency — Design

**Date:** 2026-08-10
**Author:** Vinay Rongala (decisions) + agent (research, design)
**Status:** Approved for sandbox implementation. Production promotion is NOT in scope.

---

## Goal

Cut voice-agent turn latency toward the lowest value physically reachable on
Indian PSTN, and measure honestly what that value is.

**Vinay's stated target is 500 ms ear-side** (caller stops speaking → caller
hears audio). This design does **not** promise that number and explains why in
§2. It targets **≤800 ms server-side / ≤1,000 ms p95**, and commits to
producing the first ear-side measurement this project has ever had.

**Hard scope constraint (Vinay, 2026-08-10): every change lands in the
`vachanam-agent-sandbox` Fly app only.** No change is promoted to
`vachanam-agent`. Production behaviour must be byte-identical before and after
this work.

---

## 1. Where the time goes today

Measured from Redis `lat:turns`, sandbox session `ee2b1c96`, 10 turns, real
Telugu PSTN call, prompt cache hitting on every turn. p50 `total_ms` = 1,392.

| Stage | Measured | Notes |
|---|---|---|
| STT finalise | 383–456 ms | Includes Mumbai→Tokyo RTT (~260 ms) plus finalisation |
| LLM TTFT | 410–473 ms | Gemini 2.5 Flash, Vertex `asia-south1`, cache hit |
| TTS first audio | 89–105 ms clean, 317–353 ms degraded | Cartesia `sonic-3`; degradation analysed in §5 |
| Unaccounted | ~400–500 ms | VAD hangover, endpoint commit, serialisation, playout gap |

**Every knob in the published optimisation playbooks is already turned.**
Verified in `agent/livekit_minimal/agent.py`: endpointing min 0 / max 0.06 s,
Silero VAD `min_silence_duration=0.06`, `MultilingualModel` turn detector,
`preemptive_generation.enabled=True`, TTS prewarm in `prewarm()`, Vertex
prompt caching, tool prefetch, `max_tool_steps=2`, streaming TTS.

The remaining latency is therefore **structural, not tunable**: two of the
three stages run on the wrong side of a network boundary or on a model chosen
for quality rather than speed.

---

## 2. Why 500 ms ear-side is probably not reachable

Ear-side latency decomposes as:

```
inbound carrier leg + our server-side processing + outbound carrier leg
+ jitter buffer + playout
```

We control only the middle term. Indian mobile PSTN one-way transport is
typically 100–250 ms, and both legs count.

Every published "500 ms" architecture measures **WebRTC, not PSTN**:

- Cerebrium's 500 ms budget is 110 ms STT + 300 ms LLM + 80 ms TTS + ~10 ms
  in-VPC network. No telephone network in the path.
- Prodinit's "sub-400 ms p50 in production" is likewise a WebRTC figure.
- The Openbenchmarks study, which *does* measure over real phone calls, found
  medians of 1,296–1,740 ms across five major platforms — none of them close
  to 500 ms ear-side.

The honest conclusion: **no one is achieving 500 ms ear-side over PSTN**, and a
design that promised it would be lying. What is reachable is roughly 800 ms
server-side and roughly 1,000 ms ear-side, which would place Vachanam ahead of
every platform in that study.

If Phase 0 measures the PSTN tax as unexpectedly small, this conclusion gets
revisited with a number rather than an assumption.

---

## 3. Approach

Four phases. Each is independently reversible, carries an environment-variable
kill switch (no deploy required to disable), and is gated on evidence produced
by an earlier phase.

```
Phase 0  Measure        PSTN tax + Telugu eval corpus        gates 2 and 3
Phase 1  TTS socket     −230 ms, no vendor change            independent
Phase 2  STT bake-off   −200-260 ms IF accuracy holds        gated on 0b
Phase 3  LLM swap       −150-300 ms IF quality holds         gated on 0b
```

Phases 1, 2 and 3 are independent of each other. Abandoning any one does not
block the others.

### Which sandbox each phase runs in

The existing `vachanam-agent-sandbox` (Soniox STT + Cartesia TTS) carries
Phases 1 and 3 — both are single-variable changes to a stack we already have
live telemetry for, and reusing it keeps the comparison honest.

Phase 2 gets **a new app, `vachanam-agent-stt`**, because an STT swap changes
the recogniser under a stack we are simultaneously changing elsewhere; running
it in the same app would confound the two results. It is created the same way
(`infra/fly.agent-stt-sandbox.toml`, distinct `LIVEKIT_AGENT_NAME`
`vachanam-stt`) so it can never be dispatched a real call either.

Most of Phase 2 needs no app at all: the corpus scoring runs offline against
recorded audio. The app exists only for the final live confirmation of the
winning recogniser.

---

## 4. Phase 0 — Measure

Produces the two artefacts every later decision depends on. Writes no agent
code.

### 0a. PSTN tax

**What:** record the caller side of one sandbox call. For each turn, measure
in the recording the interval from the caller's last word to the first audible
agent audio. Subtract our server-side `from_last_word_ms` for the same turn.

**Deliverable:** a single number (the tax, with its spread), and
`docs/pitch/BENCHMARKS.md` restated so our figures are directly comparable to
the Openbenchmarks ear-side numbers.

**Why it gates everything:** without it, "500 ms ear-side" is undefined, and we
cannot judge whether Phases 2 and 3 are worth their accuracy risk.

### 0b. Telugu evaluation corpus

**What:** 30–50 real Telugu utterances harvested from call audio, hand
transcribed once, stored as a test fixture. Must include the token classes that
actually break bookings: patient names, dates, clock times, doctor names, and
the romanised/native cancellation vocabulary that caused FIXLOG #511.

**Deliverable:**
- a fixture file of `(audio, reference transcript, token class)` rows
- a scoring script that runs any recogniser against it and reports overall word
  error rate **plus a separate error rate for names / dates / times**

**Why the breakout matters:** a recogniser that transcribes prose well and
appointment times badly is worse than the current one — it books the wrong slot
confidently. A single aggregate WER would hide exactly the failure that costs
a clinic a patient.

---

## 5. Phase 1 — TTS socket reacquisition

### The evidence

`_preemptive_tts_enabled()` in `agent/livekit_minimal/agent.py` already records
the mechanism: a cancelled speculative synthesis stream makes the Cartesia
plugin treat its WebSocket as broken and evict it from the pool, costing
161–258 ms reacquisition and 300–390 ms first audio on the next response.

That function already disables preemptive TTS for Cartesia. **Yet session
`ee2b1c96` still shows the signature**: 89–105 ms first audio on turns 1–4,
then 317–353 ms on turns 5–10. A different cancellation path is evicting the
socket.

### Prime suspect

FIXLOG #509 added `sess.interrupt()` in `on_user_turn_completed` whenever the
agent is `thinking` or `speaking`, to stop duplicate answers. That cancels the
synthesis stream. Any turn where the caller speaks over the agent would evict
the socket — which matches the observed pattern, since early turns are clean
and later turns are where a caller starts interrupting.

This is a hypothesis, not a finding. It is the agent's own recent change and is
named here so it is checked first rather than defended.

### Design

**Instrument before fixing.** Add a cancellation trace that records, for every
synthesis-stream cancellation, which path caused it — supersede (#509),
barge-in (#510), mutation protection (#361), or deterministic confirm — and
mirror it alongside the existing per-turn `lat:turns` line so it can be
correlated with `tts_ttfb_ms` on the same turn.

One sandbox call then names the path. The fix is chosen by what it turns out to
be:

- if supersede: exempt Cartesia from the interrupt, or make the interrupt spare
  the synthesis socket
- if barge-in or another path: hold a warm spare socket so eviction costs
  nothing

**No vendor change, no new dependency.** Kill switch: the instrumentation is
log-only; any behavioural fix ships behind its own flag.

**Expected:** −230 ms on the affected turns, and a p95 that stops depending on
whether the caller interrupted.

---

## 6. Phase 2 — STT bake-off

Gated on the Phase 0b corpus existing.

### Candidates

| Candidate | Region | Expectation |
|---|---|---|
| Soniox (baseline) | Japan | current accuracy, current latency — the control |
| Soniox v4 | query for a closer region | unknown; one API query settles it |
| Deepgram Nova-3, `X-Region-Override: asia-south1` | Mumbai | fastest; Telugu error rate documented as materially worse |
| Sarvam | India | in-region; an adapter existed historically |

### Decision rule — fixed before the experiment runs

Move off Soniox only if the candidate satisfies **both**:

1. overall word error rate on the corpus **within 2 percentage points absolute**
   of Soniox's, and
2. error rate on the **names / dates / times** token class **no worse at all**
   than Soniox's — zero tolerance, because an error here books the wrong slot

The 2-point allowance on general prose exists because the language model
recovers from ordinary transcription noise; it cannot recover from a
confidently wrong time.

If no candidate clears both, **keep Soniox**. That is a legitimate outcome and
the phase closes having bought certainty rather than latency.

**Expected if it clears:** −200 to −260 ms (removal of the Mumbai→Tokyo round
trip).

Kill switch: `STT_PROVIDER`, which already exists and already selects the
recogniser at session build.

---

## 7. Phase 3 — LLM swap

Gated on the Phase 0b corpus and the existing behavioural suites.

**Candidate: Gemini 2.5 Flash-Lite on the same Vertex `asia-south1`.** Same
region, same prompt-cache machinery, same vendor — the change is a model
identifier behind an environment variable.

**Groq is explicitly rejected.** Its sub-200 ms TTFT is real but it is
US-hosted; the Mumbai round trip consumes most of the gain, and it would add a
vendor with no Indian region to the critical path of a clinic's phone line.

### Gate

- TTFT measured on real sandbox calls, not synthetic prompts
- `docs/CALL_TORTURE_SCRIPT.md` passes against the sandbox
- the tool-calling suites pass unchanged

A faster model that routes to the wrong doctor, skips `check_availability`, or
loses the Telugu register is a regression regardless of its TTFT.

**Expected if it clears:** −150 to −300 ms.

---

## 8. Testing and safety

- **Sandbox only.** `vachanam-agent-sandbox` registers under the LiveKit agent
  name `vachanam-sandbox`, so it is never dispatched a call unless a dispatch
  rule names it explicitly. Production code paths must be unchanged; any shared
  file changed for this work must leave the `soniox` / production branch
  byte-identical.
- **Every phase behind an environment-variable kill switch**, flipped without a
  deploy — the pattern `TTS_PROVIDER` already uses.
- **The 2,402-test suite stays green.** The concurrency, tenant-isolation and
  booking-integrity suites are the hard gate; a latency change that touches
  them is rejected regardless of its numbers.
- **Latency proven on a ≥30-turn corpus**, read from `lat:turns` — not one
  call. This also retires the `n = 9` caveat currently attached to the tail
  claim in `docs/pitch/BENCHMARKS.md`.
- **No production promotion in this spec.** Promotion of any phase is a
  separate decision with its own evidence.

---

## 9. Success criteria

| | Today | Target |
|---|---|---|
| Server-side p50 | 1,392 ms | **≤ 800 ms** |
| Server-side p95 | 1,556 ms | **≤ 1,000 ms** |
| Ear-side p50 | never measured | **measured and published** |
| Telugu WER (corpus) | never measured | **no worse than today** |
| Names/dates/times WER | never measured | **no worse than today** |
| Test suite | 2,402 green | 2,402 green |
| Production behaviour | — | **unchanged** |

---

## 10. Risks

| Risk | Mitigation |
|---|---|
| The voice path is latency-tuned and prod-validated; changing it has historically caused regressions | Sandbox only; kill switch per phase; torture script before any promotion |
| The #509 supersede fix may be the cause of the TTS degradation — reverting it could bring back duplicate answers | Instrument first; if confirmed, fix narrowly (exempt the synthesis socket) rather than reverting the behaviour |
| An in-region recogniser degrades Telugu in ways an aggregate WER hides | Token-class breakout is part of the decision rule, not an afterthought |
| A faster model degrades tool calling silently | Torture script plus tool suites are gates, not checks |
| The sandbox competes for real calls if the agent name is misconfigured | Deploy check greps for `agent_name: vachanam-sandbox` before anything else — already in the runbook |
| PSTN tax turns out to dominate, making the whole exercise low-value | That is exactly what Phase 0a is for, and it is the cheapest phase |

---

## 11. Sources

Research informing this design:

- [Vapi — How we solved latency](https://vapi.ai/blog/how-we-solved-latency-at-vapi) — dynamic endpoint routing, statistical fallback thresholds; 1,200 ms turn budget
- [Cerebrium — Global-scale voice agent with 500 ms latency](https://cerebrium.ai/blog/deploying-a-global-scale-ai-voice-agent-with-500ms-latency) — self-hosted STT/LLM/TTS in one VPC, ~2 ms inter-service; the 500 ms reference architecture
- [Prodinit — Production voice AI latency architecture](https://prodinit.com/blog/production-voice-ai-agents-latency-architecture) — per-stage budget, `endpointing=300`, sub-400 ms p50 claim
- [FutureAGI — Optimise voice agent latency](https://futureagi.com/blog/how-to-optimize-voice-agent-latency-2026/) — 12 techniques with per-technique savings
- [FutureAGI — Optimise LiveKit latency](https://futureagi.com/blog/how-to-optimize-livekit-latency-2026/) — LiveKit parameter values and expected savings
- [FutureAGI — Barge-in and turn taking](https://futureagi.com/blog/voice-ai-barge-in-turn-taking-2026/) — endpointing costs, progressive turn-taking
- [Decagon — Beyond latency](https://decagon.ai/blog/beyond-latency-the-art-of-building-a-truly-great-voice-agent)
- [AG2 — LiveAgent](https://docs.ag2.ai/latest/docs/blog/2026/05/12/LiveAgent/)
- [AgentixLabs blog](https://www.agentixlabs.com/blog/)
- [Openbenchmarks — Voice agent end-to-end latency](https://openbenchmarks.com/voice-agent-latency/voice-agent-end-to-end-latency) — the ear-side study
- [Deepgram STT — LiveKit docs](https://docs.livekit.io/agents/models/stt/deepgram/) — `X-Region-Override: asia-south1`
- [Soniox vs Deepgram (Telugu)](https://soniox.com/compare/soniox-vs-deepgram/telugu) — Telugu accuracy comparison
